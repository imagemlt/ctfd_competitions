#coding=utf-8
from flask import render_template, request, redirect, jsonify, url_for, session, Blueprint, abort

from CTFd.models import db, Challenges, Files, Solves, WrongKeys, Keys, Tags, Teams, Awards, Hints, Unlocks

from CTFd.utils import admins_only, is_admin

from sqlalchemy.sql.expression import union_all
from CTFd import utils
#from CTFd.scoreboard import get_standings

from CTFd.plugins import register_plugin_assets_directory
from CTFd.plugins.challenges import get_chal_class

import datetime


competitions = Blueprint('competitions', __name__,
						 static_folder='assets', template_folder='templates')

#竞赛模型
class Competitions(db.Model):
	id = db.Column(db.Integer, primary_key=True)
	title = db.Column(db.String(46))
	description = db.Column(db.Text)
	startTime = db.Column(db.DateTime, default=datetime.datetime.utcnow)
	endTime = db.Column(db.DateTime, default=datetime.datetime.utcnow)
	profile = db.Column(db.String(50), default='default.jpg')
	chals = db.relationship('Chalcomp', backref='competition')

	def __init__(self, title, description):
		self.title = title
		self.description = description


# 存放题目与竞赛的对应关系
class Chalcomp(db.Model):
	id = db.Column(db.Integer, primary_key=True)
	chalid = db.Column(db.Integer, db.ForeignKey('challenges.id'))
	compid = db.Column(db.Integer, db.ForeignKey('competitions.id'))





def get_range(comp, admin=False, count=None, teamid=None):
	Comp = Competitions.query.filter(Competitions.id == comp).first()
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
	chals = [x.chalid for x in Comp.chals]
	if not admin and freeze:
		scores = scores.filter(Solves.date < utils.unix_time_to_utc(freeze))
		awards = awards.filter(Awards.date < utils.unix_time_to_utc(freeze))
	"""
	Combine awards and solves with a union. They should have the same amount of columns
	"""
	scores = scores.filter(Chalcomp.compid == Comp.id)
	scores = scores.filter(Solves.date < Comp.endTime)
	scores = scores.filter(Solves.date > Comp.startTime)
	#awards=scores.filter(Solves.chalid in chals)
	results = union_all(scores, awards).alias('results')
	if(teamid is not None):
		scores = scores.filter(Solves.teamid == teamid)
		awards = awards.filter(Solves.teamid == teamid)
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


@competitions.route('/competitions', defaults={'compid':None})
@competitions.route('/competitions/<int:compid>')
def comps(compid):
	if not utils.is_admin():
		if not utils.ctftime():
			if utils.view_after_ctf():
				pass
			else:
				abort(403)
	if compid is None:
		return render_template('competitions.html')
	else:
		comp=Competitions.query.filter(Competitions.id==compid).one()
		if comp:
			return render_template('comp.html',comp=comp)
		else:
			abort(403)

@competitions.route('/comps',defaults={'compid':None})
@competitions.route('/comps/<int:compid>')
def competitions_json(compid):
	if not utils.is_admin():
		if not utils.ctftime():
			if utils.view_after_ctf():
				pass
			else:
				abort(403)
	if compid is None:	
		comps= Competitions.query.all()
		json={'competitions':[]}
		for x in comps:
			json['competitions'].append({
				'id': x.id,
				'title': x.title,
				'description': x.description,
				'startTime': x.startTime,
				'endTime': x.endTime,
				'profile': x.profile
				})
		json['competitions'] = sorted(json['competitions'], key=lambda k: k['startTime'])
		json['competitions'].reverse()
		db.session.close()
		return jsonify(json)
	else:
		x=Competitions.query.filter(Competitions.id==compid).first()
		db.session.close()
		if x is None:
			abort(403)
		return jsonify({
			'id': x.id,
			'title': x.title,
			'description': x.description,
			'startTime': x.startTime,
			'endTime': x.endTime,
			'profile': x.profile
		})



@competitions.route('/admin/competitions', methods=['GET'])
@admins_only
def admin_competitions():
		comp=Competitions.query.all()
		return render_template('admin_competitions.html',comp=comp)

@competitions.route('/competitions/<int:compid>/challenges', methods=['GET'])
def challenges_view(compid):
	infos = []
	errors = []
	start = utils.get_config('start') or 0
	end = utils.get_config('end') or 0
	comp=Competitions.query.filter(Competitions.id==compid).first()
	
	if utils.ctf_paused():
		infos.append('{} is paused'.format(utils.ctf_name()))
	if not utils.is_admin():  # User is not an admin
		if not utils.ctftime():
			# It is not CTF time
			if utils.view_after_ctf():  # But we are allowed to view after the CTF ends
				pass
			else:  # We are NOT allowed to view after the CTF ends
				if utils.get_config('start') and not utils.ctf_started():
					errors.append('{} has not started yet'.format(utils.ctf_name()))
				if (utils.get_config('end') and utils.ctf_ended()) and not utils.view_after_ctf():
					errors.append('{} has ended'.format(utils.ctf_name()))
				if comp is None:
					errors.append('no such competition')
					start=False
				if comp.startTime>datetime.datetime.utcnow():
					errors=append('{} 尚未开始，敬请期待'.format(comp.title))
					start=False
				return render_template('comp_challenges.html', infos=infos, errors=errors, start=int(start), end=int(end),comp=comp)

	if utils.get_config('verify_emails'):
		if utils.authed():
			if utils.is_admin() is False and utils.is_verified() is False:  # User is not confirmed
				return redirect(url_for('auth.confirm_user'))

	if utils.user_can_view_challenges():  # Do we allow unauthenticated users?
		if utils.get_config('start') and not utils.ctf_started():
			errors.append('{} has not started yet'.format(utils.ctf_name()))
		if (utils.get_config('end') and utils.ctf_ended()) and not utils.view_after_ctf():
			errors.append('{} has ended'.format(utils.ctf_name()))
		if comp is None:
			errors.append('no such competition')
			start=False
		if comp.startTime>datetime.datetime.utcnow():
			errors.append('{} 尚未开始，敬请期待'.format(comp.title))
			start=False
		return render_template('comp_challenges.html', infos=infos, errors=errors, start=int(start), end=int(end),comp=comp)
	else:
		return redirect(url_for('auth.login', next=request.path))

#@competitions.route('/competitions/<compid>', methods=['GET'])
#def comp_chals(compid):
#	if not utils.is_admin():
#		if not utils.ctftime():
#			if utils.view_after_ctf():
#				pass
#			else:
#				abort(403)
#	if utils.get_config('verify_emails'):
#		if utils.authed():
#			if utils.is_admin() is False and utils.is_verified() is False:  # User is not confirmed
#				abort(403)
#	if utils.user_can_view_challenges() and (utils.ctf_started() or utils.is_admin()):
#		teamid = session.get('id')
#		comp = Competitions.query.filter(Competitions.id == compid).first()
#		if comp is None:
#			abort(403)
#		if comp.startTime>datetime.datetime.utcnow():
#			abort(403)
#		return render_template('competition.html', competition=comp)
#	else:
#		abort(403)


@competitions.route('/competitions/<int:compid>/chals', methods=['GET'])
def comp_challenges(compid):
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
		comp = Competitions.query.filter(Competitions.id == compid).first()
		if comp is None:
			abort(403)
		if comp.startTime>datetime.datetime.utcnow():
			abort(403)
		#chals=comp.chals
		json = {
			'competition': {
				'id': comp.id,
				'title': comp.title,
				'description': comp.description,
				'startTime': comp.startTime,
				'endTime': comp.endTime
				},
			'game': []
				}
		for x in comp.chals:
			chal = Challenges.query.filter(Challenges.id == x.chalid).first()
			if chal is None:
				abort(502)
			tags = [tag.tag for tag in Tags.query.add_columns('tag').filter(Tags.chal == chal.id).all()]
			files = [str(f.location) for f in Files.query.filter(Files.chal == chal.id).all()]
			unlocked_hints = set([u.itemid for u in Unlocks.query.filter(Unlocks.model == 'hints', Unlocks.teamid == teamid)])
			hints = []
			for hint in Hints.query.filter(Hints.chal == chal.id).all():
				if hint.id in unlocked_hints or utils.ctf_ended():
					hints.append({'id': hint.id, 'cost': hint.cost, 'hint': hint.hint})
				else:
					hints.append({'id': hint.id, 'cost': hint.cost})
			chal_type = get_chal_class(chal.type)
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


@competitions.route('/admin/competitions/add', methods=['GET','POST'])
@admins_only
def addComp():
	if request.method == 'GET':
		return render_template('add_comp.html')
	elif request.method == 'POST':
		title = request.form.get('title')
		description = request.form.get('description')
		startTime = request.form.get('startTime')
		endTime = request.form.get('endTime')
		profile = request.form.get('profile')
		comp = Competitions(title, description)
		comp.startTime = datetime.datetime.strptime(startTime, '%Y-%m-%d %H:%M:%S')
		comp.endTime = datetime.datetime.strptime(endTime, '%Y-%m-%d %H:%M:%S')
		comp.profile = profile
		db.session.add(comp)
		db.session.flush()
		db.session.commit()
		return redirect('/admin/competitions')

@competitions.route('/admin/competitions/<int:compid>/del',methods=['DELETE'])
@admins_only
def del_comp(compid):
	try:
		comp=Competitions.query.filter(Competitions.id==compid).first()
		db.session.delete(comp)
		chalcomps=Chalcomp.query.filter(Chalcomp.compid==compid).all()
		for x in chalcomps:
			x.compid=1
		db.session.commit()
		return jsonify({'res':'success'})
	except Exception,e:
		return jsonify({'res':'fail'})
		

@competitions.route('/admin/competitions/<int:compid>/edit',methods=['GET','POST'])
@admins_only
def editcomp(compid):
	comp=Competitions.query.filter(Competitions.id==compid).first()
	if comp is None:
		abort(403)
	if(request.method=='GET'):
		return render_template('/add_comp.html',comp=comp)
	else:
		title = request.form.get('title')
		description = request.form.get('description')
		startTime = request.form.get('startTime')
		endTime = request.form.get('endTime')
		profile = request.form.get('profile')
		comp.title = title
		comp.description = description
		comp.startTime = datetime.datetime.strptime(startTime, '%Y-%m-%d %H:%M:%S')
		comp.endTime = datetime.datetime.strptime(endTime, '%Y-%m-%d %H:%M:%S')
		comp.profile = profile
		db.session.commit()
		return redirect('/admin/competitions')
		
		

@competitions.route('/competitions/<int:compid>/scores')
def scores(compid):
	json = {'standings': []}
	if utils.get_config('view_scoreboard_if_authed') and not utils.authed():
		return redirect(url_for('auth.login', next=request.path))
	if utils.hide_scores():
		return jsonify(json)

	standings = get_range(comp=compid)

	for i, x in enumerate(standings):
		json['standings'].append(
					{'pos': i + 1, 'id': x.teamid, 'team': x.name, 'score': int(x.score)})
	return jsonify(json)


@competitions.route('/competitions/<int:compid>/top/<int:count>')
def topteams(compid, count):
	json = {'places': {}}
	if utils.get_config('view_scoreboard_if_authed') and not utils.authed():
		return redirect(url_for('auth.login', next=request.path))
	if utils.hide_scores():
		return jsonify(json)

	if count > 20 or count < 0:
		count = 10

	standings = get_range(comp=compid, count=count)

	team_ids = [team.teamid for team in standings]
	chalids = [chal.chalid for chal in Chalcomp.query.filter(
		Chalcomp.compid == compid)]
	solves = Solves.query.filter(Solves.teamid.in_(team_ids))
	solves = Solves.query.filter(Solves.chalid.in_(chalids))
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
		json['places'][i +1]['solves'] = sorted(json['places'][i + 1]['solves'], key=lambda k: k['time'])

	return jsonify(json)


@competitions.route('/competitions/<int:compid>/scoreboard')
def comp_scoreboard(compid):
	if utils.get_config('view_scoreboard_if_authed') and not utils.authed():
		return redirect(url_for('auth.login', next=request.path))
	if utils.hide_scores():
		print 'error!'
		return render_template('compet_scoreboard.html', errors=['Scores are currently hidden'])
	comp=Competitions.query.filter(Competitions.id==compid).first()
	if comp is None:
		abort(404)
	standings = get_range(comp=compid)
	return render_template('compet_scoreboard.html', teams=standings, score_frozen=utils.is_scoreboard_frozen(),comp=comp)



@competitions.route('/competitions/<int:compid>/chalboard/solves/<int:teamid>')
def team_solves(compid, teamid):
	json = {'solves': []}
	if utils.get_config('view_scoreboard_if_authed') and not utils.authed():
		return redirect(url_for('auth.login', next=request.path))
	if utils.hide_scores():
		return jsonify(json)

	chalids = [chal.chalid for chal in Chalcomp.query.filter(
			Chalcomp.compid == compid)]
	solves = Solves.query.filter(Solves.teamid == teamid)
	awards = Awards.query.filter(Awards.teamid == teamid)
	solves = solves.filter(Solves.chalid.in_(chalids))
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


@competitions.route('/competitions/<int:compid>/solves')
@competitions.route('/competitions/<int:compid>/solves/<int:teamid>')
def solves(compid,teamid=None):
	solves = None
	awards = None
	comp=Competitions.query.filter(Competitions.id==compid).first()
	if comp is None:
		abort(403)
	if teamid is None:
		if utils.is_admin():
			solves = Solves.query.filter_by(teamid=session['id']).all()
		elif utils.user_can_view_challenges():
			if utils.authed():
				chalids = [chal.chalid for chal in Chalcomp.query.filter(
				Chalcomp.compid == compid)]
				solves = Solves.query.join(Teams, Solves.teamid == Teams.id).filter(Solves.teamid == session['id'], Teams.banned == False,Solves.chalid.in_(chalids)).all()
			else:
				return jsonify({'solves': []})
		else:
			return redirect(url_for('auth.login', next=request.path))
	else:
		if utils.authed() and session['id'] == teamid:
			solves = Solves.query.filter_by(teamid=teamid)
			awards = Awards.query.filter_by(teamid=teamid)

			freeze = utils.get_config('freeze')
			if freeze:
				freeze = utils.unix_time_to_utc(freeze)
				if teamid != session.get('id'):
					solves = solves.filter(Solves.date < freeze)
					awards = awards.filter(Awards.date < freeze)
			
			chalids = [chal.chalid for chal in Chalcomp.query.filter(
			Chalcomp.compid == compid)]
			print chalids
			solves=solves.filter(Solves.chalid.in_(chalids))
			solves = solves.all()
			awards = awards.all()
		elif utils.hide_scores():
			# Use empty values to hide scores
			solves = []
			awards = []
		else:
			solves = Solves.query.filter_by(teamid=teamid)
			awards = Awards.query.filter_by(teamid=teamid)

			freeze = utils.get_config('freeze')
			if freeze:
				freeze = utils.unix_time_to_utc(freeze)
				if teamid != session.get('id'):
					solves = solves.filter(Solves.date < freeze)
					awards = awards.filter(Awards.date < freeze)
			chalids = [chal.chalid for chal in Chalcomp.query.filter(
				Chalcomp.compid == compid)]
			print chalids
			solves=solves.filter(Solves.chalid.in_(chalids))
			solves = solves.all()
			awards = awards.all()
	db.session.close()
	json = {'solves': []}
	for solve in solves:
		json['solves'].append({
			'chal': solve.chal.name,
			'chalid': solve.chalid,
			'team': solve.teamid,
			'value': solve.chal.value,
			'category': solve.chal.category,
			'time': utils.unix_time(solve.date)
		})
	if awards:
		for award in awards:
			json['solves'].append({
				'chal': award.name,
				'chalid': None,
				'team': award.teamid,
				'value': award.value,
				'category': award.category or "Award",
				'time': utils.unix_time(award.date)
			})
	json['solves'].sort(key=lambda k: k['time'])
	return jsonify(json)

@competitions.route('/admin/competitions/<int:compid>/chals', methods=['POST', 'GET'])
@admins_only
def admin_chals(compid):
	comp=Competitions.query.filter(Competitions.id==compid).first()
	if not comp:
		abort(403)
	if request.method == 'POST':
		chalids=[x.chalid for x in Chalcomp.query.filter(Chalcomp.compid==compid).all()]
		chals = Challenges.query.filter(Challenges.id.in_(chalids)).order_by(Challenges.value).all()

		json_data = {'game': []}
		for chal in chals:
			tags = [tag.tag for tag in Tags.query.add_columns('tag').filter_by(chal=chal.id).all()]
			files = [str(f.location) for f in Files.query.filter_by(chal=chal.id).all()]
			hints = []
			for hint in Hints.query.filter_by(chal=chal.id).all():
				hints.append({'id': hint.id, 'cost': hint.cost, 'hint': hint.hint})

			type_class = CHALLENGE_CLASSES.get(chal.type)
			type_name = type_class.name if type_class else None

			json_data['game'].append({
				'id': chal.id,
				'name': chal.name,
				'value': chal.value,
				'description': chal.description,
				'category': chal.category,
				'files': files,
				'tags': tags,
				'hints': hints,
				'hidden': chal.hidden,
				'max_attempts': chal.max_attempts,
				'type': chal.type,
				'type_name': type_name,
				'type_data': {
					'id': type_class.id,
					'name': type_class.name,
					'templates': type_class.templates,
					'scripts': type_class.scripts,
				}
			})

		db.session.close()
		return jsonify(json_data)
	else:
		chalids=[x.chalid for x in Chalcomp.query.filter(Chalcomp.compid==compid).all()]
		challenges = Challenges.query.filter(Challenges.id.in_(chalids)).all()
		return render_template('admin_chals.html', challenges=challenges,comp=comp)

@competitions.route('/admin/competitions/<int:compid>/chal/new', methods=['GET', 'POST'])
@admins_only
def admin_create_chal(compid):
	comp=Competitions.query.filter(Competitions.id==compid).first()
	if not comp:
		abort(403)
	if request.method == 'POST':
		chal_type = request.form['chaltype']
		chal_class = get_chal_class(chal_type)
		chal_class.create(request)
		chalid=db.session.query(db.func.max(Challenges.id)).one()[0]
		chalcomp=Chalcomp()
		chalcomp.chalid=chalid
		chalcomp.compid=compid
		db.session.add(chalcomp)
		db.session.commit()
		db.session.flush()
		return redirect('/admin/competitions/'+str(compid)+'/chals')
	else:
		return render_template('add_chals.html',comp=comp)

def load(app):
	register_plugin_assets_directory(
			app, base_path='/plugins/competitions/assets/')
	app.register_blueprint(competitions)
	app.db.create_all()
