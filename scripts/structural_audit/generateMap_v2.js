const { Project, SyntaxKind } = require("ts-morph");
const fs = require("fs");
const path = require("path");

const project = new Project();
project.addSourceFilesAtPaths("frontend/{app,components,hooks,lib,i18n}/**/*.{ts,tsx}");

let mapContent = "// 🧠 FRONTEND ARCHITECTURE MAP (Auto-generated via ts-morph)\n\n";

const hubTracker = {};

project.getSourceFiles().forEach(file => {
    const filePath = path.relative(process.cwd(), file.getFilePath());
    mapContent += `### FILE: ${filePath}\n`;

    const imports = file.getImportDeclarations();
    if (imports.length > 0) {
        const importPaths = imports.map(i => i.getModuleSpecifierValue());
        const localImports = importPaths.filter(p => p.startsWith(".") || p.startsWith("@/"));
        const extImports = importPaths.filter(p => !p.startsWith(".") && !p.startsWith("@/"));
        
        if (localImports.length > 0) {
            mapContent += `[local_deps]: ${localImports.join(", ")}\n`;
        }
        if (extImports.length > 0) {
            mapContent += `[ext_deps]: ${extImports.join(", ")}\n`;
        }
        
        localImports.forEach(dep => {
            hubTracker[dep] = (hubTracker[dep] || 0) + 1;
        });
    }

    file.getExportedDeclarations().forEach((declarations, name) => {
        declarations.forEach(decl => {
            const kind = decl.getKind();
            if (kind === SyntaxKind.FunctionDeclaration) {
                const func = decl.asKind(SyntaxKind.FunctionDeclaration);
                mapContent += `[fn]: ${name}(${func?.getParameters().map(p => p.getName()).join(", ")})\n`;
            } else if (kind === SyntaxKind.ArrowFunction) {
                mapContent += `[fn]: ${name}(arrow_fn)\n`;
            } else if (kind === SyntaxKind.ClassDeclaration) {
                const cls = decl.asKind(SyntaxKind.ClassDeclaration);
                const methods = cls?.getMethods().map(m => m.getName()).join(", ");
                mapContent += `[class]: ${name} { methods: [${methods}] }\n`;
            } else if (kind === SyntaxKind.InterfaceDeclaration) {
                const intf = decl.asKind(SyntaxKind.InterfaceDeclaration);
                const props = intf?.getProperties().map(p => p.getName()).join(", ");
                mapContent += `[interface]: ${name} { props: [${props}] }\n`;
            } else if (kind === SyntaxKind.TypeAliasDeclaration) {
                mapContent += `[type]: ${name}\n`;
            } else {
                mapContent += `[export]: ${name}\n`;
            }
        });
    });

    mapContent += "\n---\n";
});

const topHubs = Object.entries(hubTracker)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15);

const hubHeader = `// 🧠 TOP ARCHITECTURAL HUBS (Most Imported Local Modules)\n` +
    topHubs.map(([mod, count]) => `// [hub]: ${mod} → imported ${count} times`).join("\n") +
    `\n\n`;

mapContent = hubHeader + mapContent;

const outPath = path.join(process.cwd(), "scripts", "structural_audit", "cache.graph.frontend.ts");
fs.writeFileSync(outPath, mapContent);
console.log("✅ Frontend cache.graph.frontend.ts generated successfully.");
console.log(`📊 Top 5 Hubs:`);
topHubs.slice(0,5).forEach(([mod, count]) => console.log(`   ${mod}: ${count} imports`));
