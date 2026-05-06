import { Project, SyntaxKind } from "ts-morph";
import * as fs from "fs";
import * as path from "path";

const project = new Project();
// Include frontend source, exclude build artifacts and node_modules
project.addSourceFilesAtPaths("frontend/{app,components,hooks,lib,i18n}/**/*.{ts,tsx}");

let mapContent = "// 🧠 FRONTEND ARCHITECTURE MAP (Auto-generated via ts-morph)\n\n";

const hubTracker: Record<string, number> = {};

project.getSourceFiles().forEach(file => {
    const filePath = path.relative(process.cwd(), file.getFilePath());
    mapContent += `### FILE: ${filePath}\n`;

    // 1. Extract Imports (Dependencies)
    const imports = file.getImportDeclarations();
    if (imports.length > 0) {
        const importPaths = imports.map(i => i.getModuleSpecifierValue()).filter(p => !p.startsWith("."));
        const localImports = imports.map(i => i.getModuleSpecifierValue()).filter(p => p.startsWith("."));
        
        if (localImports.length > 0) {
            mapContent += `[local_deps]: " + localImports.join(", ") + "\n`;
        }
        if (importPaths.length > 0) {
            mapContent += `[ext_deps]: " + importPaths.join(", ") + "\n`;
        }
        
        // Track hubs
        localImports.forEach(dep => {
            hubTracker[dep] = (hubTracker[dep] || 0) + 1;
        });
    }

    // 2. Extract Exports & Signatures (Interfaces)
    file.getExportedDeclarations().forEach((declarations, name) => {
        declarations.forEach(decl => {
            if (decl.getKind() === SyntaxKind.FunctionDeclaration) {
                const func = decl.asKind(SyntaxKind.FunctionDeclaration);
                mapContent += `[fn]: ${name}(${func?.getParameters().map(p => p.getName()).join(", ")})\n`;
            } else if (decl.getKind() === SyntaxKind.ArrowFunction) {
                mapContent += `[fn]: ${name}(arrow_fn)\n`;
            } else if (decl.getKind() === SyntaxKind.ClassDeclaration) {
                const cls = decl.asKind(SyntaxKind.ClassDeclaration);
                const methods = cls?.getMethods().map(m => m.getName()).join(", ");
                mapContent += `[class]: ${name} { methods: [${methods}] }\n`;
            } else if (decl.getKind() === SyntaxKind.InterfaceDeclaration) {
                const intf = decl.asKind(SyntaxKind.InterfaceDeclaration);
                const props = intf?.getProperties().map(p => p.getName()).join(", ");
                mapContent += `[interface]: ${name} { props: [${props}] }\n`;
            } else if (decl.getKind() === SyntaxKind.TypeAliasDeclaration) {
                mapContent += `[type]: ${name}\n`;
            } else if (decl.getKind() === SyntaxKind.VariableDeclaration) {
                mapContent += `[export]: ${name}\n`;
            }
        });
    });

    mapContent += "\n---\n";
});

// Hub analysis
const topHubs = Object.entries(hubTracker)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10);

mapContent = `// 🧠 TOP ARCHITECTURAL HUBS (Most Imported Local Modules)\n` +
    topHubs.map(([mod, count]) => `// [hub]: ${mod} → imported ${count} times`).join("\n") +
    `\n\n` + mapContent;

const outPath = path.join(process.cwd(), "scripts", "structural_audit", "cache.graph.frontend.ts");
fs.writeFileSync(outPath, mapContent);
console.log("✅ Frontend cache.graph.frontend.ts generated successfully.");
console.log(`📊 Top Hub: ${topHubs[0]?.[0] || 'N/A'} (${topHubs[0]?.[1] || 0} imports)`);
