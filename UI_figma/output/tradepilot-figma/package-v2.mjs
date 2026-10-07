import fs from 'node:fs';
import path from 'node:path';
const source=path.dirname(new URL(import.meta.url).pathname),target=path.join(source,'..','TradePilot-Figma-UI');
fs.mkdirSync(target,{recursive:true});
for(const name of ['code.js','README.md','design.json']){
 const p=path.join(target,name),backup=path.join(target,name+'.before-v2');
 if(fs.existsSync(p)&&!fs.existsSync(backup))fs.copyFileSync(p,backup);
}
const instructions=fs.readFileSync(path.join(source,'UPDATE-v2.md'),'utf8');
fs.writeFileSync(path.join(source,'README.md'),instructions);
for(const name of fs.readdirSync(source))if(/^(code\.js|manifest\.json|design\.json|README\.md|UPDATE-v2\.md|verification\.json|screen-\d+\.(svg|png)|TradePilot-.*\.(svg|png))$/.test(name))fs.copyFileSync(path.join(source,name),path.join(target,name));
console.log('Updated the installed folder: '+target);
