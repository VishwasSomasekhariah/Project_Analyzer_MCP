#!/usr/bin/env python3
"""
Project Metadata Enhancement: Include non-code files in CPG analysis

CURRENT PROBLEM:
- Only process source code files via tree-sitter/LSP
- Ignore config files, docs, build files that contain crucial project metadata
- Missing project dependencies, build info, documentation structure

PROPOSAL: Hybrid approach for cross-language project metadata capture
"""

import os
import json
from pathlib import Path

def analyze_project_metadata_files(project_path="/opt/HelloWorldApp"):
    """Analyze what non-code files exist in a typical project"""

    print("🔍 Project Metadata Analysis")
    print("=" * 60)
    print(f"📁 Project: {project_path}")

    # Define cross-language file categories
    file_categories = {
        "package_management": {
            "patterns": ["package.json", "pom.xml", "requirements.txt", "Cargo.toml", "go.mod", "*.csproj", "Gemfile", "composer.json"],
            "description": "Dependency and package management"
        },
        "build_config": {
            "patterns": ["Makefile", "Dockerfile", "docker-compose.yml", "build.gradle", "CMakeLists.txt", "*.sln"],
            "description": "Build and deployment configuration"
        },
        "environment_config": {
            "patterns": [".env", "appsettings.json", "web.config", "application.properties", "config.yaml", "settings.py"],
            "description": "Runtime environment and application settings"
        },
        "ci_cd": {
            "patterns": [".github/workflows/*", ".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml", ".circleci/config.yml"],
            "description": "CI/CD pipeline configuration"
        },
        "documentation": {
            "patterns": ["README.md", "CHANGELOG.md", "docs/*", "*.md", "LICENSE"],
            "description": "Project documentation and legal files"
        },
        "ide_config": {
            "patterns": [".vscode/*", ".idea/*", "*.editorconfig", ".gitignore", ".gitattributes"],
            "description": "IDE and development environment configuration"
        }
    }

    found_files = {}
    total_files = 0

    # Scan project directory
    for root, dirs, files in os.walk(project_path):
        # Skip common ignore directories
        dirs[:] = [d for d in dirs if d not in ['.git', 'node_modules', 'bin', 'obj', '__pycache__', '.vs']]

        for file in files:
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, project_path)

            # Skip source code files we already process
            if file.endswith(('.cs', '.java', '.py', '.js', '.ts', '.cpp', '.c', '.h', '.go', '.rs')):
                continue

            # Categorize non-code files
            categorized = False
            for category, info in file_categories.items():
                for pattern in info["patterns"]:
                    if (pattern.endswith('*') and file.startswith(pattern[:-1])) or \
                       (pattern.startswith('*') and file.endswith(pattern[1:])) or \
                       (pattern in rel_path) or \
                       (file == pattern):
                        if category not in found_files:
                            found_files[category] = []
                        found_files[category].append({
                            "file": rel_path,
                            "size": os.path.getsize(file_path),
                            "path": file_path
                        })
                        categorized = True
                        total_files += 1
                        break
                if categorized:
                    break

    # Display results
    print(f"\n📊 Non-Code Files Found: {total_files}")

    for category, info in file_categories.items():
        if category in found_files:
            print(f"\n📂 {category.upper().replace('_', ' ')}")
            print(f"   {info['description']}")
            for file_info in found_files[category][:5]:  # Show first 5
                size_kb = file_info['size'] / 1024
                print(f"   ✅ {file_info['file']} ({size_kb:.1f}KB)")
            if len(found_files[category]) > 5:
                print(f"   ... and {len(found_files[category]) - 5} more")

    return found_files

def propose_project_enhancement():
    """Propose how to enhance Project node with metadata"""

    print("\n" + "=" * 60)
    print("🎯 PROPOSED ENHANCEMENT: Hybrid Approach")
    print("=" * 60)

    proposal = """
APPROACH: Hybrid Project Metadata Capture

1. ENHANCED PROJECT NODE PROPERTIES:
   Add structured metadata properties to Project node:

   Project:
     attributes: [
       ...,
       "dependencies",           # Parsed from package.json, pom.xml, etc.
       "build_config",          # Key build settings
       "environment_config",    # Important env/app settings
       "documentation_summary", # README content, key docs
       "ci_cd_info",           # Pipeline configuration summary
       "project_type",         # "nodejs", "dotnet", "java", "python", etc.
       "metadata_files"        # List of all non-code files
     ]

2. ENHANCED FILE NODES:
   Create File nodes for non-code files with metadata:

   File:
     attributes: [
       ...,
       "file_category",        # "package_management", "build_config", etc.
       "parsed_content",       # Structured content for JSON/XML/YAML
       "content_summary"       # Key information extracted
     ]

3. CROSS-LANGUAGE PROCESSING:

   JavaScript/Node.js:
   - Parse package.json → dependencies, scripts, engines
   - Parse .env → environment variables
   - Parse webpack.config.js → build settings

   Java:
   - Parse pom.xml/build.gradle → dependencies, plugins, properties
   - Parse application.properties → configuration settings

   .NET/C#:
   - Parse *.csproj → package references, target framework
   - Parse appsettings.json → configuration settings

   Python:
   - Parse requirements.txt/setup.py/pyproject.toml → dependencies
   - Parse .env → environment settings

   Docker:
   - Parse Dockerfile → base images, exposed ports, commands
   - Parse docker-compose.yml → services, networks, volumes

4. BENEFITS:
   ✅ Complete project understanding (not just code)
   ✅ Dependency analysis and security scanning
   ✅ Build and deployment insights
   ✅ Documentation context for RAG queries
   ✅ Environment-specific configurations
   ✅ Cross-language consistency

5. IMPLEMENTATION STRATEGY:
   - File Detection: Pattern-based file categorization
   - Content Parsing: Format-specific parsers (JSON, XML, YAML, etc.)
   - Metadata Extraction: Key information extraction per file type
   - Project Aggregation: Roll up important info to Project node
   - Relationship Creation: Link configs to relevant code components
"""

    print(proposal)

def demonstrate_config_parsing():
    """Show example of parsing HelloWorldApp project files"""

    print("\n" + "=" * 60)
    print("📋 EXAMPLE: HelloWorldApp Config Parsing")
    print("=" * 60)

    project_path = "/opt/HelloWorldApp"

    # Look for .csproj file
    csproj_files = []
    for root, dirs, files in os.walk(project_path):
        for file in files:
            if file.endswith('.csproj'):
                csproj_files.append(os.path.join(root, file))

    if csproj_files:
        print(f"\n📁 Found .csproj file: {csproj_files[0]}")
        try:
            with open(csproj_files[0], 'r') as f:
                content = f.read()
                print("\n📄 Content:")
                print(content[:500] + "..." if len(content) > 500 else content)

                # Extract key information
                if '<TargetFramework>' in content:
                    import re
                    framework = re.search(r'<TargetFramework>(.*?)</TargetFramework>', content)
                    if framework:
                        print(f"\n✅ Target Framework: {framework.group(1)}")

                if '<PackageReference' in content:
                    packages = re.findall(r'<PackageReference Include="(.*?)" Version="(.*?)"', content)
                    if packages:
                        print("✅ Package Dependencies:")
                        for pkg, version in packages:
                            print(f"   - {pkg} ({version})")

        except Exception as e:
            print(f"❌ Error reading .csproj: {e}")

    # Look for other config files
    other_configs = []
    for root, dirs, files in os.walk(project_path):
        for file in files:
            if file in ['appsettings.json', 'web.config', 'Dockerfile', 'README.md']:
                other_configs.append(os.path.join(root, file))

    if other_configs:
        print(f"\n📁 Other config files found:")
        for config in other_configs:
            rel_path = os.path.relpath(config, project_path)
            size = os.path.getsize(config)
            print(f"   ✅ {rel_path} ({size} bytes)")

if __name__ == "__main__":
    # Analyze current project
    found_files = analyze_project_metadata_files()

    # Show enhancement proposal
    propose_project_enhancement()

    # Demonstrate parsing
    demonstrate_config_parsing()

    print(f"\n🎯 SUMMARY:")
    print(f"Current CPG captures: Code files only")
    print(f"Missing metadata: {sum(len(files) for files in found_files.values())} non-code files")
    print(f"Enhancement impact: Complete project understanding + dependency analysis")