var competitions = {};
function update() {
    $.ajax({
        'type': "GET",
        'url': script_root + "/comps",
        'dataType': "json",
        'success': function (data) {
            console.log(data);
            competitions = data;
            $.get(script_root + '/plugins/competitions/assets/compet.hbs', function (temp) {
                var template = nunjucks.compile(temp);
                var wrapper = { competitions: competitions.competitions ,script_root:script_root};
                $('#content').html(template.render(wrapper));
            })
        }
    })
}
update();
setInterval(update, 10000);
