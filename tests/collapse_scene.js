// The two header shapes that actually exist in the report, plus the three
// shapes that must be LEFT ALONE.
var HDRFLEX='background:var(--bg-page);padding:8px 14px;font-size:9px;font-weight:700;'+
            'letter-spacing:.12em;color:var(--tx2);text-transform:uppercase;display:flex;'+
            'align-items:center;justify-content:space-between;';
var HDRFLOAT='background:var(--bg-page);padding:8px 14px;font-size:9px;font-weight:700;'+
             'letter-spacing:.12em;color:var(--tx2);text-transform:uppercase;margin:-14px -14px 10px;';

// 1. a plain CARD with a FLEX header, carrying a note that changes every day
var card = mk('div','background:var(--bg-card);border-radius:6px;');
var h1   = mk('div',HDRFLEX); h1.appendChild(mk('span','','Morning Overview'));
h1.appendChild(mk('span','','PREMARKET 7:45AM CT'));
var b1   = mk('div','padding:14px;','overview body');
card.appendChild(h1); card.appendChild(b1);

// 2. a flex ROW whose right column carries a FLOAT header and two body siblings
var row  = mk('div','display:flex;gap:1px;');
var colL = mk('div','flex:0 0 27%;display:flex;flex-direction:column;');
var colR = mk('div','flex:0 0 73%;padding:14px;display:flex;flex-direction:column;');
var h2   = mk('div',HDRFLOAT,'Strat Setups');
h2.appendChild(mk('span','float:right;','FRIDAY 10/2 CLOSE'));
var b2a  = mk('div','','setup 1'), b2b = mk('div','','setup 2');
colR.appendChild(h2); colR.appendChild(b2a); colR.appendChild(b2b);
row.appendChild(colL); row.appendChild(colR);

// 3. a card inside the COLUMN-flex left column - align-self here shrinks it sideways
var card2= mk('div','background:var(--bg-card);');
var h3   = mk('div',HDRFLEX); h3.appendChild(mk('span','','Top Setups'));
var b3   = mk('div','','rows');
card2.appendChild(h3); card2.appendChild(b3); colL.appendChild(card2);

// 4. a header with no body
var card3= mk('div',''); var h4=mk('div',HDRFLEX); h4.appendChild(mk('span','','Empty'));
card3.appendChild(h4);

// 5. a matching div that is NOT a first child - not a section header
var card4= mk('div','');
card4.appendChild(mk('div','','something above'));
var h5   = mk('div',HDRFLEX); h5.appendChild(mk('span','','Not A Section'));
card4.appendChild(h5); card4.appendChild(mk('div','','body'));
