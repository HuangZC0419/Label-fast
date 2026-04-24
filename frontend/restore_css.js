
const fs = require('fs');
const path = require('path');

const distPath = path.join('dist', 'assets', 'index-BabP2RLM.css');
const srcPath = path.join('src', 'App.css');

try {
    const content = fs.readFileSync(distPath, 'utf8');
    const formatted = content.replace(/\}/g, '}\n').replace(/\{/g, ' {\n').replace(/;/g, ';\n');
    fs.writeFileSync(srcPath, formatted);
    console.log(`Restored ${srcPath}`);
} catch (err) {
    console.error(err);
    process.exit(1);
}
