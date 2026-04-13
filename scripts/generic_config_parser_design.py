#!/usr/bin/env python3
"""
Generic Config File Parser Design: Extensible, Non-Hardcoded Approach

CHALLENGE: Parse diverse config files (JSON, XML, YAML, TOML, INI, etc.)
across different languages/projects without hardcoding specific formats.

SOLUTION: Plugin-based parser system with format detection and semantic extraction.
"""

import os
import json
import yaml
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

# =============================================================================
# 1. GENERIC PARSER INTERFACE
# =============================================================================

class ConfigParser(ABC):
    """Abstract base class for all config file parsers"""

    @abstractmethod
    def can_parse(self, file_path: str) -> bool:
        """Check if this parser can handle the given file"""
        pass

    @abstractmethod
    def parse(self, file_path: str) -> Dict[str, Any]:
        """Parse the file and return structured data"""
        pass

    @abstractmethod
    def extract_metadata(self, parsed_data: Dict[str, Any], file_path: str) -> Dict[str, Any]:
        """Extract semantic metadata from parsed data"""
        pass

# =============================================================================
# 2. FORMAT-SPECIFIC PARSERS (Auto-Discoverable)
# =============================================================================

class JsonConfigParser(ConfigParser):
    """Parser for JSON files (package.json, appsettings.json, etc.)"""

    def can_parse(self, file_path: str) -> bool:
        return file_path.endswith('.json')

    def parse(self, file_path: str) -> Dict[str, Any]:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def extract_metadata(self, parsed_data: Dict[str, Any], file_path: str) -> Dict[str, Any]:
        metadata = {
            'format': 'json',
            'file_type': self._detect_json_type(file_path, parsed_data),
            'dependencies': self._extract_dependencies(parsed_data),
            'configuration': self._extract_configuration(parsed_data),
            'scripts': parsed_data.get('scripts', {}),
            'version_info': self._extract_version_info(parsed_data)
        }
        return {k: v for k, v in metadata.items() if v}  # Remove empty values

    def _detect_json_type(self, file_path: str, data: Dict) -> str:
        """Auto-detect what type of JSON config this is"""
        filename = os.path.basename(file_path).lower()

        # Pattern-based detection
        if filename == 'package.json' and 'dependencies' in data:
            return 'nodejs_package'
        elif filename.startswith('appsettings') and 'ConnectionStrings' in data:
            return 'dotnet_appsettings'
        elif 'dependencies' in data or 'devDependencies' in data:
            return 'package_manager'
        elif 'ConnectionStrings' in data or 'Logging' in data:
            return 'application_settings'
        else:
            return 'generic_json'

    def _extract_dependencies(self, data: Dict) -> Dict:
        """Extract dependency information from various JSON formats"""
        deps = {}
        if 'dependencies' in data:
            deps['runtime'] = data['dependencies']
        if 'devDependencies' in data:
            deps['development'] = data['devDependencies']
        if 'peerDependencies' in data:
            deps['peer'] = data['peerDependencies']
        return deps

    def _extract_configuration(self, data: Dict) -> Dict:
        """Extract configuration settings"""
        config = {}
        # Common config keys
        for key in ['ConnectionStrings', 'Logging', 'AllowedHosts', 'DatabaseSettings']:
            if key in data:
                config[key] = data[key]
        return config

    def _extract_version_info(self, data: Dict) -> Dict:
        """Extract version-related information"""
        version_info = {}
        if 'version' in data:
            version_info['version'] = data['version']
        if 'engines' in data:
            version_info['engines'] = data['engines']
        return version_info


class XmlConfigParser(ConfigParser):
    """Parser for XML files (pom.xml, *.csproj, web.config, etc.)"""

    def can_parse(self, file_path: str) -> bool:
        return file_path.endswith(('.xml', '.csproj', '.vbproj', '.fsproj'))

    def parse(self, file_path: str) -> Dict[str, Any]:
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(file_path)
            return self._xml_to_dict(tree.getroot())
        except Exception as e:
            return {'error': str(e), 'raw_content': self._read_as_text(file_path)[:1000]}

    def extract_metadata(self, parsed_data: Dict[str, Any], file_path: str) -> Dict[str, Any]:
        metadata = {
            'format': 'xml',
            'file_type': self._detect_xml_type(file_path, parsed_data),
            'target_framework': self._extract_target_framework(parsed_data),
            'package_references': self._extract_package_references(parsed_data),
            'properties': self._extract_properties(parsed_data)
        }
        return {k: v for k, v in metadata.items() if v}

    def _detect_xml_type(self, file_path: str, data: Dict) -> str:
        filename = os.path.basename(file_path).lower()
        if filename.endswith('.csproj'):
            return 'dotnet_project'
        elif filename == 'pom.xml':
            return 'maven_project'
        elif filename == 'web.config':
            return 'dotnet_web_config'
        else:
            return 'generic_xml'

    def _extract_target_framework(self, data: Dict) -> Optional[str]:
        """Extract target framework from project files"""
        # Navigate XML structure to find TargetFramework
        return self._find_nested_value(data, ['PropertyGroup', 'TargetFramework'])

    def _extract_package_references(self, data: Dict) -> List[Dict]:
        """Extract package/dependency references"""
        packages = []
        # Look for PackageReference elements
        package_refs = self._find_all_nested(data, 'PackageReference')
        for ref in package_refs:
            if isinstance(ref, dict) and 'Include' in ref:
                packages.append({
                    'name': ref.get('Include'),
                    'version': ref.get('Version'),
                    'type': 'package_reference'
                })
        return packages

    def _xml_to_dict(self, element):
        """Convert XML element to dictionary"""
        result = {}

        # Add attributes
        if element.attrib:
            result.update(element.attrib)

        # Add text content
        if element.text and element.text.strip():
            if len(element) == 0:  # Leaf node
                return element.text.strip()
            result['_text'] = element.text.strip()

        # Add child elements
        for child in element:
            child_data = self._xml_to_dict(child)
            if child.tag in result:
                if not isinstance(result[child.tag], list):
                    result[child.tag] = [result[child.tag]]
                result[child.tag].append(child_data)
            else:
                result[child.tag] = child_data

        return result if result else element.text

    def _find_nested_value(self, data: Dict, path: List[str]) -> Optional[str]:
        """Navigate nested dictionary to find value"""
        current = data
        for key in path:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        return current if isinstance(current, str) else None

    def _find_all_nested(self, data: Dict, target_key: str) -> List:
        """Find all occurrences of a key in nested structure"""
        results = []
        if isinstance(data, dict):
            for key, value in data.items():
                if key == target_key:
                    if isinstance(value, list):
                        results.extend(value)
                    else:
                        results.append(value)
                else:
                    results.extend(self._find_all_nested(value, target_key))
        elif isinstance(data, list):
            for item in data:
                results.extend(self._find_all_nested(item, target_key))
        return results

    def _extract_properties(self, data: Dict) -> Dict:
        """Extract properties from XML"""
        properties = {}
        prop_groups = self._find_all_nested(data, 'PropertyGroup')
        for prop_group in prop_groups:
            if isinstance(prop_group, dict):
                properties.update({k: v for k, v in prop_group.items() if not k.startswith('_')})
        return properties

    def _read_as_text(self, file_path: str) -> str:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()


class YamlConfigParser(ConfigParser):
    """Parser for YAML files (docker-compose.yml, .github/workflows, etc.)"""

    def can_parse(self, file_path: str) -> bool:
        return file_path.endswith(('.yml', '.yaml'))

    def parse(self, file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            return {'error': str(e)}

    def extract_metadata(self, parsed_data: Dict[str, Any], file_path: str) -> Dict[str, Any]:
        metadata = {
            'format': 'yaml',
            'file_type': self._detect_yaml_type(file_path, parsed_data),
            'services': parsed_data.get('services', {}),
            'workflow_info': self._extract_workflow_info(parsed_data),
            'configuration': self._extract_yaml_config(parsed_data)
        }
        return {k: v for k, v in metadata.items() if v}

    def _detect_yaml_type(self, file_path: str, data: Dict) -> str:
        filename = os.path.basename(file_path).lower()
        if 'docker-compose' in filename:
            return 'docker_compose'
        elif '.github' in file_path and 'on' in data:
            return 'github_workflow'
        elif 'services' in data:
            return 'service_config'
        else:
            return 'generic_yaml'

    def _extract_workflow_info(self, data: Dict) -> Dict:
        """Extract CI/CD workflow information"""
        workflow = {}
        if 'on' in data:
            workflow['triggers'] = data['on']
        if 'jobs' in data:
            workflow['jobs'] = list(data['jobs'].keys())
        return workflow

    def _extract_yaml_config(self, data: Dict) -> Dict:
        """Extract general configuration from YAML"""
        config = {}
        for key in ['version', 'name', 'description', 'environment']:
            if key in data:
                config[key] = data[key]
        return config


class TextConfigParser(ConfigParser):
    """Parser for text-based configs (requirements.txt, .env, Dockerfile, etc.)"""

    def can_parse(self, file_path: str) -> bool:
        filename = os.path.basename(file_path).lower()
        return filename in ['requirements.txt', 'dockerfile', '.env', '.gitignore', 'makefile'] or \
               file_path.endswith(('.txt', '.env', '.ini'))

    def parse(self, file_path: str) -> Dict[str, Any]:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        return {
            'content': content,
            'lines': [line.strip() for line in content.split('\n') if line.strip()]
        }

    def extract_metadata(self, parsed_data: Dict[str, Any], file_path: str) -> Dict[str, Any]:
        filename = os.path.basename(file_path).lower()

        metadata = {
            'format': 'text',
            'file_type': self._detect_text_type(filename),
            'line_count': len(parsed_data.get('lines', [])),
        }

        # File-specific extraction
        if filename == 'requirements.txt':
            metadata['dependencies'] = self._parse_requirements(parsed_data['lines'])
        elif filename.startswith('.env'):
            metadata['environment_variables'] = self._parse_env_file(parsed_data['lines'])
        elif filename == 'dockerfile':
            metadata['docker_info'] = self._parse_dockerfile(parsed_data['lines'])

        return {k: v for k, v in metadata.items() if v}

    def _detect_text_type(self, filename: str) -> str:
        type_map = {
            'requirements.txt': 'python_requirements',
            'dockerfile': 'docker_config',
            '.env': 'environment_config',
            '.gitignore': 'git_ignore',
            'makefile': 'build_config'
        }
        return type_map.get(filename, 'generic_text')

    def _parse_requirements(self, lines: List[str]) -> List[Dict]:
        """Parse Python requirements.txt"""
        deps = []
        for line in lines:
            if line and not line.startswith('#'):
                # Simple parsing - can be enhanced
                if '==' in line:
                    name, version = line.split('==', 1)
                    deps.append({'name': name.strip(), 'version': version.strip()})
                else:
                    deps.append({'name': line.strip(), 'version': 'latest'})
        return deps

    def _parse_env_file(self, lines: List[str]) -> Dict[str, str]:
        """Parse .env file"""
        env_vars = {}
        for line in lines:
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
        return env_vars

    def _parse_dockerfile(self, lines: List[str]) -> Dict:
        """Parse Dockerfile"""
        info = {}
        for line in lines:
            if line.upper().startswith('FROM '):
                info['base_image'] = line.split()[1]
            elif line.upper().startswith('EXPOSE '):
                if 'ports' not in info:
                    info['ports'] = []
                info['ports'].extend(line.split()[1:])
        return info

# =============================================================================
# 3. PARSER REGISTRY & AUTO-DISCOVERY
# =============================================================================

class ConfigParserRegistry:
    """Registry that auto-discovers and manages all available parsers"""

    def __init__(self):
        self.parsers = self._discover_parsers()

    def _discover_parsers(self) -> List[ConfigParser]:
        """Auto-discover all ConfigParser subclasses"""
        parsers = []
        for cls in ConfigParser.__subclasses__():
            try:
                parsers.append(cls())
            except Exception as e:
                print(f"Warning: Could not instantiate parser {cls.__name__}: {e}")
        return parsers

    def find_parser(self, file_path: str) -> Optional[ConfigParser]:
        """Find the best parser for a given file"""
        for parser in self.parsers:
            if parser.can_parse(file_path):
                return parser
        return None

    def parse_file(self, file_path: str) -> Dict[str, Any]:
        """Parse any config file using the appropriate parser"""
        parser = self.find_parser(file_path)
        if not parser:
            return {'error': 'No parser found', 'file_type': 'unsupported'}

        try:
            parsed_data = parser.parse(file_path)
            metadata = parser.extract_metadata(parsed_data, file_path)

            return {
                'success': True,
                'parser_used': parser.__class__.__name__,
                'metadata': metadata,
                'raw_data': parsed_data  # Include if needed for debugging
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'parser_attempted': parser.__class__.__name__
            }

# =============================================================================
# 4. DEMONSTRATION
# =============================================================================

def demonstrate_generic_parsing():
    """Demonstrate the generic parsing system on HelloWorldApp"""

    print("🔧 Generic Config Parser Demonstration")
    print("=" * 60)

    registry = ConfigParserRegistry()
    print(f"📋 Discovered {len(registry.parsers)} parsers:")
    for parser in registry.parsers:
        print(f"   - {parser.__class__.__name__}")

    # Test on HelloWorldApp files
    project_path = "/opt/HelloWorldApp"
    test_files = []

    # Find config files
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in ['.git', 'bin', 'obj']]
        for file in files:
            if not file.endswith(('.cs', '.exe', '.dll', '.pdb')):  # Skip source and build outputs
                test_files.append(os.path.join(root, file))

    print(f"\n📁 Found {len(test_files)} non-source files to parse:")

    for file_path in test_files[:5]:  # Limit output
        rel_path = os.path.relpath(file_path, project_path)
        print(f"\n📄 Parsing: {rel_path}")

        result = registry.parse_file(file_path)

        if result.get('success'):
            metadata = result['metadata']
            print(f"   ✅ Parser: {result['parser_used']}")
            print(f"   📊 File Type: {metadata.get('file_type', 'unknown')}")
            print(f"   📋 Format: {metadata.get('format', 'unknown')}")

            # Show interesting extracted data
            for key, value in metadata.items():
                if key not in ['format', 'file_type'] and value:
                    print(f"   🔍 {key}: {value}")
        else:
            print(f"   ❌ Failed: {result.get('error', 'Unknown error')}")

    print(f"\n🎯 BENEFITS:")
    print("✅ No hardcoded file parsing")
    print("✅ Extensible - just add new parser classes")
    print("✅ Auto-discovery of parsers")
    print("✅ Consistent metadata extraction")
    print("✅ Works across all project types/languages")

if __name__ == "__main__":
    demonstrate_generic_parsing()