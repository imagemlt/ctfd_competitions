#coding=utf-8
from flask import render_template, request, redirect, jsonify, url_for, session, Blueprint,abort

from CTFd.models import db, Challenges, Files, Solves, WrongKeys, Keys, Tags, Teams, Awards, Hints, Unlocks

from CTFd.utils import admins_only, is_admin

from sqlalchemy.sql.expression import union_all
from CTFd import utils
#from CTFd.scoreboard import get_standings

from CTFd.plugins import register_plugin_assets_directory
from CTFd.plugins.challenges import get_chal_class

import datetime

# 竞赛模型
competitions=Blueprint('competitions',__name__,static_folder='assets',template_folder='templates')


class Competitions(db.Model):
		id = db.Column(db.Integer, primary_key=True)
		title = db.Column(db.String(46))
		description = db.Column(db.Text)
		startTime = db.Column(db.DateTime, default=datetime.datetime.utcnow)
		endTime = db.Column(db.DateTime, default=datetime.datetime.utcnow)
		profile=db.Column(db.String(50),default='default.jpg')
		chals=db.relationship('Chalcomp',backref='competition')

		def __init__(self, title, description):
			self.title = title
			self.description = description
		

# 存放题目与竞赛的对应关系
class Chalcomp(db.Model):
		id = db.Column(db.Integer, primary_key=True)
		chalid = db.Column(db.Integer,db.ForeignKey('challenges.id'))
		compid = db.Column(db.Integer,db.ForeignKey('competitions.id'))




#def team_solves(compid,teamid):
#	comp=Competitions.query.filter(Competitions.id==compid).first()
#	if not comp:
#		return None
#	chalcomp=Chalcomp.query.filter(Chalcomp.id==compid).all()
#	ans=[]
#	for x in chalcomp:
#		for s in solves:
			
	

def get_range(comp,admin=False,count=None,teamid=None):
	Comp=Competitions.query.filter(Competitions.id==comp).first()
	if not Comp:
		return []
	scores = db.session.query(
		Solves.teamid.label('teamid'),
		db.func.sum(Challenges.value).label('score'),
		db.func.max(Solves.id).label('id'),
		db.func.max(Solves.date).label('date')
	).join(Challenges).join(Chalcomp).group_by(Solves.teamid)
	awards = db.session.query(
		Awards.teamid.label('teamid'),
		db.func.sum(Awards.value).label('score'),
		db.func.max(Awards.id).label('id'),
		db.func.max(Awards.date).label('date')
	).group_by(Awards.teamid)
	"""
	Filter out solves and awards that are before a specific time point.
	"""
	freeze = utils.get_config('freeze')
	chals=[x.chalid for x in Comp.chals]
	if not admin and freeze:
		scores = scores.filter(Solves.date < utils.unix_time_to_utc(freeze))
		awards = awards.filter(Awards.date < utils.unix_time_to_utc(freeze))
	"""
	Combine awards and solves with a union. They should have the same amount of columns
	"""
	scores=scores.filter(Chalcomp.compid==Comp.id)
	scores=scores.filter(Solves.date<Comp.endTime)
	scores=scores.filter(Solves.date>Comp.startTime)
	#awards=scores.filter(Solves.chalid in chals)
	results = union_all(scores, awards).alias('results')
	print results
	if(teamid is not None):
		scores=scores.filter(Solves.teamid==teamid)
		awards=awards.filter(Solves.teamid==teamid)
	"""
	Sum each of the results by the team id to get their score.
	"""
	sumscores = db.session.query(
		results.columns.teamid,
		db.func.sum(results.columns.score).label('score'),
		db.func.max(results.columns.id).label('id'),
		db.func.max(results.columns.date).label('date')
	).group_by(results.columns.teamid).subquery()

	"""
	Admins can see scores for all users but the public cannot see banned users.

	Filters out banned users.
	Properly resolves value ties by ID.

	Different databases treat time precision differently so resolve by the row ID instead.
	"""
	if admin:
		standings_query = db.session.query(
			Teams.id.label('teamid'),
			Teams.name.label('name'),
			Teams.banned, sumscores.columns.score
		)\
			.join(sumscores, Teams.id == sumscores.columns.teamid) \
			.order_by(sumscores.columns.score.desc(), sumscores.columns.id)
	else:
		standings_query = db.session.query(
			Teams.id.label('teamid'),
			Teams.name.label('name'),
			sumscores.columns.score
		)\
			.join(sumscores, Teams.id == sumscores.columns.teamid) \
			.filter(Teams.banned == False) \
			.order_by(sumscores.columns.score.desc(), sumscores.columns.id)
	#print standings_query

	"""
	Only select a certain amount of users if asked.
	"""
	if count is None:
		standings = standings_query.all()
	else:
		standings = standings_query.limit(count).all()
	db.session.close()

	return standings




@competitions.route('/competitions',methods=['GET'])
def comps():
		if not utils.is_admin():
			if not utils.ctftime():
					if utils.view_after_ctf():
						pass
					else:
						abort(403)
		return render_template('competitions.html')

@competitions.route('/comps', methods=['GET'])
def competitions_json():
		if not utils.is_admin():
			if not utils.ctftime():
					if utils.view_after_ctf():
						pass
					else:
						abort(403)
		if utils.user_can_view_challenges() and (utils.ctf_started() or utils.is_admin()):
			competitions = Competitions.query.all()
			json = {'competitions': []}
			for x in competitions:
					json['competitions'].append({
								'id': x.id,
								'title': x.title,
								'description': x.description,
								'startTime':x.startTime,
								'endTime':x.endTime,
								'profile':x.profile
					})
			db.session.close()
			return jsonify(json)
		else:
			db.session.close()
			abort(403)
					


@competitions.route('/admin/competitions', methods=['GET'])
@admins_only
def admin_competitions():
		return render_template('admin_competitions.html')

@competitions.route('/admin/competitions/<compid>',methods=['GET'])
def comp_chals(compid):
		if not utils.is_admin():
			if not utils.ctftime():
					if utils.view_after_ctf():
						pass
					else:
						abort(403)
		if utils.get_config('verify_emails'):
			if utils.authed():
				if utils.is_admin() is False and utils.is_verified() is False:  # User is not confirmed
					abort(403)
		if utils.user_can_view_challenges() and (utils.ctf_started() or utils.is_admin()):
			teamid = session.get('id')
			comp=Competitions.query.filter(Competitions.id==compid).first()
			if comp is None:
				abort(403)
		comp=Competitions.query.filter(Competitions.id==compid).one()
		if comp:
			return render_template('competition.html',competition=comp)
		else:
			abort(404)



@competitions.route('/challenges/comp/<compid>', methods=['GET'])
def challenges_view(compid):
		if not utils.is_admin():
			if not utils.ctftime():
					if utils.view_after_ctf():
						pass
					else:
						abort(403)
		if utils.get_config('verify_emails'):
			if utils.authed():
				if utils.is_admin() is False and utils.is_verified() is False:  # User is not confirmed
					abort(403)
		if utils.user_can_view_challenges() and (utils.ctf_started() or utils.is_admin()):
			teamid = session.get('id')
			comp=Competitions.query.filter(Competitions.id==compid).first()
			if comp is None:
				abort(403)
			if not comp.started():
				abort(403)
			#chals=comp.chals
			json = {
					'competition':{
						'id':comp.id,
						'title':comp.title,
						'description':comp.description,
						'startTime':comp.startTime,
						'endTime':comp.endTime
					},
					'game':[]
				}
			for x in comp.chals:
				chal=Challenges.query.filter(Challenges.id==x.chalid).first()
				if chal is None:
					abort(502)
				tags = [tag.tag for tag in Tags.query.add_columns('tag').filter(Tags.chal==chal.id).all()]
				files = [str(f.location) for f in Files.query.filter(Files.chal==chal.id).all()]
				unlocked_hints = set([u.itemid for u in Unlocks.query.filter(Unlocks.model=='hints', Unlocks.teamid==teamid)])
				hints = [] 
				for hint in Hints.query.filter(Hints.chal==chal.id).all():
					if hint.id in unlocked_hints or utils.ctf_ended():
						hints.append({'id': hint.id, 'cost': hint.cost, 'hint': hint.hint})
					else:
						hints.append({'id': hint.id, 'cost': hint.cost})
				chal_type=get_chal_class(chal.type)
				json['game'].append({
					'id': chal.id,
					'type': chal_type.name,
					'name': chal.name,
					'value': chal.value,
					'description': chal.description,
					'category': chal.category,
					'files': files,
					'tags': tags,
					'hints': hints,
					'template': chal_type.templates['modal'],
					'script': chal_type.scripts['modal'],
				})
			db.session.close()
			return jsonify(json)
		else:
			db.session.close()
			abort(403)
	
	
	

@competitions.route('/addComp', methods=['GET'])
@admins_only
def addComp():
		if request.method == 'GET':
			return render_template('newComptition.html')
		
@competitions.route('/admin/addComp',methods=['POST'])
@admins_only
def add_comp():
		if request.method == 'POST':
			title = request.form.get('title')
			description = request.form.get('description')
			startTime = request.form.get('startTime')
			endTime = request.form.get('endTime')
			profile=request.form.get('profile')
			comp = Competitions(title, description)
			comp.startTime = startTime
			comp.endTime = endTime
			comp.profile=profile
			db.session.add(comp)
			sb.session.flush()
			db.session.commit()
			return redirect('/admin/competitions')
	
@competitions.route('/session',methods=['GET'])
def sessions():
		return 'err'

@competitions.route('/competitions/<int:compid>/scores')
def scores(compid):
	json = {'standings': []}
	if utils.get_config('view_scoreboard_if_authed') and not utils.authed():
		return redirect(url_for('auth.login', next=request.path))
	if utils.hide_scores():
		return jsonify(json)

	standings = get_range(comp=compid)

	for i, x in enumerate(standings):
		json['standings'].append({'pos': i + 1, 'id': x.teamid, 'team': x.name, 'score': int(x.score)})
	return jsonify(json)

@competitions.route('/competitions/<int:compid>/top/<int:count>')
def topteams(compid,count):
		json = {'places': {}}
		if utils.get_config('view_scoreboard_if_authed') and not utils.authed():
			return redirect(url_for('auth.login', next=request.path))
		if utils.hide_scores():
			return jsonify(json)

		if count > 20 or count < 0:
			count = 10

		standings = get_range(comp=compid,count=count)

		team_ids = [team.teamid for team in standings]

		solves = Solves.query.filter(Solves.teamid.in_(team_ids))
		awards = Awards.query.filter(Awards.teamid.in_(team_ids))

		freeze = utils.get_config('freeze')

		if freeze:
			solves = solves.filter(Solves.date < utils.unix_time_to_utc(freeze))
			awards = awards.filter(Awards.date < utils.unix_time_to_utc(freeze))

		solves = solves.all()
		awards = awards.all()

		for i, team in enumerate(team_ids):
			json['places'][i + 1] = {
				'id': standings[i].teamid,
				'name': standings[i].name,
				'solves': []
			}
			for solve in solves:
				if solve.teamid == team:
					json['places'][i + 1]['solves'].append({
						'chal': solve.chalid,
						'team': solve.teamid,
						'value': solve.chal.value,
						'time': utils.unix_time(solve.date)
					})
			for award in awards:
				if award.teamid == team:
					json['places'][i + 1]['solves'].append({
						'chal': None,
						'team': award.teamid,
						'value': award.value,
						'time': utils.unix_time(award.date)
					})
			json['places'][i + 1]['solves'] = sorted(json['places'][i + 1]['solves'], key=lambda k: k['time'])

		return jsonify(json)
		
@competitions.route('/competitions/<int:compid>/solves/<int:teamid>')
def team_solves(compid,teamid):
	json={'solves':[]}
	if utils.get_config('view_scoreboard_if_authed') and not utils.authed():
		return redirect(url_for('auth.login', next=request.path))
	if utils.hide_scores():
		return jsonify(json)

	chalids=[chal.chalid for chal in Chalcomp.query.filter(Chalcomp.compid==compid)]
	solves = Solves.query.filter(Solves.teamid==teamid)
	awards = Awards.query.filter(Awards.teamid==teamid)
	solves=solves.filter(Solves.chalid in (chalids))
	freeze = utils.get_config('freeze')

	if freeze:
		solves = solves.filter(Solves.date < utils.unix_time_to_utc(freeze))
		awards = awards.filter(Awards.date < utils.unix_time_to_utc(freeze))

	solves = solves.all()
	awards = awards.all()

	for solve in solves:
		json['solves'].append({
				'chal': solve.chalid,
				'team': solve.teamid,
				'value': solve.chal.value,
				'time': utils.unix_time(solve.date)
			})
	for award in awards:
			json['solves'].append({
				'chal': None,
				'team': award.teamid,
				'value': award.value,
				'time': utils.unix_time(award.date)
			})
	json['solves'] = sorted(json['solves'], key=lambda k: k['time'])
	return jsonify(json)




def load(app):
	register_plugin_assets_directory(
			app, base_path='/plugins/competitions/assets/')
	app.register_blueprint(competitions)
	app.db.create_all()
	
