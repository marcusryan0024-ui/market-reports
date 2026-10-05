// Minimal DOM, enough to exercise the section-collapse script in report_lib._COLLAPSE.
// Only the APIs that script actually uses are implemented; anything else is a
// deliberate hole so a new API call shows up as a failure rather than silently
// passing against a shim that pretends to support it.
var LS = {};
localStorage = { getItem:function(k){return k in LS?LS[k]:null;},
                 setItem:function(k,v){LS[k]=String(v);},
                 removeItem:function(k){delete LS[k];} };

function El(tag, style, text){
  this.tagName=tag.toUpperCase(); this.children=[]; this.parentElement=null;
  this.style={}; this._styleStr=style||''; this.dataset={}; this._text=text||'';
  this.hidden=false; this.attrs={}; this._listeners={}; this.className='';
  var self=this;
  this.classList={add:function(c){self.className=(self.className+' '+c).trim();},
                  contains:function(c){return (' '+self.className+' ').indexOf(' '+c+' ')>=0;}};
}
Object.defineProperty(El.prototype,'firstElementChild',{get:function(){return this.children[0]||null;}});
Object.defineProperty(El.prototype,'firstChild',{get:function(){
  if(this._text){return {nodeType:3,nodeValue:this._text,nextSibling:this.children[0]||null};}
  return this.children[0]||null;}});
Object.defineProperty(El.prototype,'previousElementSibling',{get:function(){
  if(!this.parentElement)return null;
  var i=this.parentElement.children.indexOf(this);
  return i>0?this.parentElement.children[i-1]:null;}});
Object.defineProperty(El.prototype,'nextElementSibling',{get:function(){
  if(!this.parentElement)return null;
  var i=this.parentElement.children.indexOf(this);
  return this.parentElement.children[i+1]||null;}});
Object.defineProperty(El.prototype,'textContent',{get:function(){
  var s=this._text; for(var i=0;i<this.children.length;i++)s+=this.children[i].textContent; return s;}});
El.prototype.appendChild=function(c){c.parentElement=this;this.children.push(c);return c;};
El.prototype.insertBefore=function(n,ref){n.parentElement=this;
  var i=ref?this.children.indexOf(ref):-1; if(i<0)i=0; this.children.splice(i,0,n); return n;};
El.prototype.setAttribute=function(k,v){this.attrs[k]=String(v);};
El.prototype.getAttribute=function(k){return k in this.attrs?this.attrs[k]:null;};
El.prototype.addEventListener=function(t,f){(this._listeners[t]=this._listeners[t]||[]).push(f);};
El.prototype.fire=function(t,ev){(this._listeners[t]||[]).forEach(function(f){
  f(ev||{target:{closest:function(){return null;}}});});};

getComputedStyle=function(el){
  var s=el._styleStr||'';
  return {display:/display:flex/.test(s)?'flex':'block',
          flexDirection:/flex-direction:column/.test(s)?'column':'row'};
};

var ALL=[];
document = {
  readyState:'complete', addEventListener:function(){},
  createElement:function(t){var e=new El(t);ALL.push(e);return e;},
  querySelectorAll:function(){
    return ALL.filter(function(e){
      return e.tagName==='DIV' && /letter-spacing:\.12em/.test(e._styleStr)
          && /text-transform:uppercase/.test(e._styleStr);});}
};
function mk(tag,style,text){var e=new El(tag,style,text);ALL.push(e);return e;}
