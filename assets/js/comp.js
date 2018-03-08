var rendererMD = new marked.Renderer();
    marked.setOptions({
      renderer: rendererMD,
      gfm: true,
      tables: true,
      breaks: false,
      pedantic: false,
      sanitize: false,
      smartLists: true,
      smartypants: false
    });
    marked.setOptions({
        highlight: function (code) {
        return hljs.highlightAuto(code).value;
      }
    });
$.getJSON(script_root+'/comps/'+compid,function(res){
    $('#content').html(marked(res.description));
})