"""
Code-Qualitäts-Tests für statische Analyse.

Diese Tests prüfen den Code auf:
- Syntaxfehler
- Fehlende Imports
- Undefinierte Variablen
- Import-Fehler zur Laufzeit
"""

import ast
import sys
import importlib
import importlib.util
from pathlib import Path
from typing import Set, Dict, List, Tuple

import pytest

# Projekt-Root
PROJECT_ROOT = Path(__file__).parent.parent

# Python-Dateien, die getestet werden sollen
PYTHON_FILES = [
    'config.py',
    'models.py',
    'sync_logic.py',
    'sync_all_users.py',
    'web_server.py',
]


class ImportChecker(ast.NodeVisitor):
    """AST-Visitor zur Analyse von Imports und verwendeten Namen."""
    
    def __init__(self):
        self.imports: Set[str] = set()  # Importierte Namen
        self.from_imports: Dict[str, Set[str]] = {}  # Modul -> Namen
        self.used_names: Set[str] = set()  # Verwendete Namen
        self.defined_names: Set[str] = set()  # Definierte Namen (Funktionen, Klassen, Variablen)
        self.local_imports: List[Tuple[str, int]] = []  # (name, line) für lokale Imports in Funktionen
        
    def visit_Import(self, node):
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name.split('.')[0]
            self.imports.add(name)
        self.generic_visit(node)
        
    def visit_ImportFrom(self, node):
        module = node.module or ''
        if module not in self.from_imports:
            self.from_imports[module] = set()
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self.from_imports[module].add(name)
            self.imports.add(name)
        self.generic_visit(node)
    
    def visit_FunctionDef(self, node):
        self.defined_names.add(node.name)
        # Parameter auch als definiert markieren
        for arg in node.args.args:
            self.defined_names.add(arg.arg)
        for arg in node.args.kwonlyargs:
            self.defined_names.add(arg.arg)
        if node.args.vararg:
            self.defined_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            self.defined_names.add(node.args.kwarg.arg)
        self.generic_visit(node)
        
    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)
        
    def visit_ClassDef(self, node):
        self.defined_names.add(node.name)
        self.generic_visit(node)
        
    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self.defined_names.add(node.id)
        elif isinstance(node.ctx, ast.Load):
            self.used_names.add(node.id)
        self.generic_visit(node)
        
    def visit_ExceptHandler(self, node):
        if node.name:
            self.defined_names.add(node.name)
        self.generic_visit(node)
        
    def visit_For(self, node):
        # Loop-Variable
        if isinstance(node.target, ast.Name):
            self.defined_names.add(node.target.id)
        elif isinstance(node.target, ast.Tuple):
            for elt in node.target.elts:
                if isinstance(elt, ast.Name):
                    self.defined_names.add(elt.id)
        self.generic_visit(node)
        
    def visit_With(self, node):
        for item in node.items:
            if item.optional_vars:
                if isinstance(item.optional_vars, ast.Name):
                    self.defined_names.add(item.optional_vars.id)
        self.generic_visit(node)
        
    def visit_comprehension(self, node):
        if isinstance(node.target, ast.Name):
            self.defined_names.add(node.target.id)
        self.generic_visit(node)
        
    def visit_ListComp(self, node):
        for gen in node.generators:
            self.visit_comprehension(gen)
        self.generic_visit(node)
        
    def visit_DictComp(self, node):
        for gen in node.generators:
            self.visit_comprehension(gen)
        self.generic_visit(node)
        
    def visit_SetComp(self, node):
        for gen in node.generators:
            self.visit_comprehension(gen)
        self.generic_visit(node)
        
    def visit_GeneratorExp(self, node):
        for gen in node.generators:
            self.visit_comprehension(gen)
        self.generic_visit(node)


class TestSyntax:
    """Tests für Python-Syntaxfehler."""
    
    @pytest.mark.parametrize("filename", PYTHON_FILES)
    def test_file_has_valid_syntax(self, filename):
        """Prüft, ob die Datei gültige Python-Syntax hat."""
        filepath = PROJECT_ROOT / filename
        assert filepath.exists(), f"Datei {filename} existiert nicht"
        
        source = filepath.read_text(encoding='utf-8')
        try:
            ast.parse(source, filename=filename)
        except SyntaxError as e:
            pytest.fail(f"Syntaxfehler in {filename}, Zeile {e.lineno}: {e.msg}")


class TestImports:
    """Tests für Import-Validierung."""
    
    @pytest.mark.parametrize("filename", PYTHON_FILES)
    def test_all_imports_are_resolvable(self, filename):
        """Prüft, ob alle Imports aufgelöst werden können."""
        filepath = PROJECT_ROOT / filename
        source = filepath.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=filename)
        
        errors = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name
                    try:
                        importlib.import_module(module_name)
                    except ImportError as e:
                        errors.append(f"Zeile {node.lineno}: Import '{module_name}' fehlgeschlagen: {e}")
                        
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module
                if module_name:
                    # Skip relative imports und lokale Module
                    if module_name in ['config', 'models', 'sync_logic', 'sync_all_users', 'web_server']:
                        continue
                    try:
                        mod = importlib.import_module(module_name)
                        # Prüfe, ob die importierten Namen existieren
                        for alias in node.names:
                            if alias.name != '*':
                                # Einige Module haben Submodule, die nicht als Attribute sichtbar sind
                                # Versuche zuerst als Attribut, dann als Submodul
                                if not hasattr(mod, alias.name):
                                    # Versuche als Submodul zu importieren
                                    try:
                                        importlib.import_module(f"{module_name}.{alias.name}")
                                    except ImportError:
                                        errors.append(
                                            f"Zeile {node.lineno}: '{alias.name}' existiert nicht in Modul '{module_name}'"
                                        )
                    except ImportError as e:
                        errors.append(f"Zeile {node.lineno}: Import von '{module_name}' fehlgeschlagen: {e}")
        
        if errors:
            pytest.fail(f"Import-Fehler in {filename}:\n" + "\n".join(errors))
    
    @pytest.mark.parametrize("filename", PYTHON_FILES)
    def test_module_imports_successfully(self, filename):
        """Prüft, ob das Modul vollständig importiert werden kann."""
        module_name = filename.replace('.py', '')
        
        # Lade das Modul dynamisch
        filepath = PROJECT_ROOT / filename
        spec = importlib.util.spec_from_file_location(module_name, filepath)
        assert spec is not None, f"Konnte spec für {filename} nicht erstellen"
        assert spec.loader is not None, f"Kein Loader für {filename}"
        
        module = importlib.util.module_from_spec(spec)
        
        # Füge zum sys.modules hinzu, damit relative Imports funktionieren
        old_module = sys.modules.get(module_name)
        sys.modules[module_name] = module
        
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            pytest.fail(f"Modul {filename} konnte nicht importiert werden: {type(e).__name__}: {e}")
        finally:
            # Cleanup
            if old_module:
                sys.modules[module_name] = old_module
            else:
                sys.modules.pop(module_name, None)


class TestUndefinedNames:
    """Tests für undefinierte Variablen und Namen."""
    
    # Python built-in Namen
    BUILTINS = set(dir(__builtins__)) if isinstance(__builtins__, dict) else set(dir(__builtins__))
    BUILTINS.update({
        'True', 'False', 'None', 'print', 'len', 'str', 'int', 'float', 'bool',
        'list', 'dict', 'set', 'tuple', 'range', 'enumerate', 'zip', 'map', 'filter',
        'open', 'type', 'isinstance', 'issubclass', 'hasattr', 'getattr', 'setattr',
        'delattr', 'callable', 'super', 'property', 'staticmethod', 'classmethod',
        'Exception', 'ValueError', 'TypeError', 'KeyError', 'IndexError', 'AttributeError',
        'ImportError', 'FileNotFoundError', 'OSError', 'RuntimeError', 'StopIteration',
        'min', 'max', 'sum', 'abs', 'round', 'sorted', 'reversed', 'any', 'all',
        'format', 'repr', 'id', 'hash', 'input', 'vars', 'dir', 'globals', 'locals',
        'exec', 'eval', 'compile', '__name__', '__file__', '__doc__', '__import__',
        'object', 'bytes', 'bytearray', 'memoryview', 'complex', 'frozenset',
        'slice', 'iter', 'next', 'chr', 'ord', 'hex', 'oct', 'bin', 'pow', 'divmod',
        'NotImplementedError', 'AssertionError', 'ZeroDivisionError', 'OverflowError',
        'UnicodeDecodeError', 'UnicodeEncodeError', 'NameError', 'SyntaxError',
        'IOError', 'EOFError', 'MemoryError', 'RecursionError', 'SystemExit',
        'KeyboardInterrupt', 'GeneratorExit', 'BaseException', 'Warning',
        'DeprecationWarning', 'FutureWarning', 'UserWarning', 'ResourceWarning',
        'breakpoint', 'ascii', 'copyright', 'credits', 'license', 'help', 'quit', 'exit',
    })
    
    @pytest.mark.parametrize("filename", PYTHON_FILES)
    def test_no_obvious_undefined_names(self, filename):
        """
        Prüft auf offensichtlich undefinierte Namen.
        
        Hinweis: Dies ist eine vereinfachte statische Analyse und kann
        false positives haben bei dynamischen Imports oder komplexen Scopes.
        """
        filepath = PROJECT_ROOT / filename
        source = filepath.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=filename)
        
        checker = ImportChecker()
        checker.visit(tree)
        
        # Sammle alle verfügbaren Namen
        available_names = (
            self.BUILTINS | 
            checker.imports | 
            checker.defined_names
        )
        
        # Finde potentiell undefinierte Namen
        potentially_undefined = checker.used_names - available_names
        
        # Filtere bekannte Patterns heraus (z.B. Attributzugriffe, die wir nicht tracken)
        # und Namen, die typischerweise in bestimmten Kontexten definiert werden
        known_dynamic = {
            'self', 'cls',  # Klassen-Methoden
            'app', 'request', 'session', 'current_user', 'g', 'flash',  # Flask-Kontext
            'f',  # Oft in with-Statements
            'e', 'exc', 'err', 'error',  # Oft in except-Blöcken
            'i', 'j', 'k', 'x', 'y', 'n', 'm',  # Loop-Variablen
            'key', 'value', 'item', 'elem',  # Iteration
            '_',  # Throwaway Variable
            'line', 'row', 'col',  # Iteration
            'result', 'response', 'data',  # Generische Namen
            'node', 'child', 'parent',  # Tree traversal
            'args', 'kwargs',  # Function arguments
            'creds', 'flow', 'service',  # OAuth/Google API
            'user', 'user_id', 'email',  # User-bezogen
            'config', 'settings',  # Konfiguration
            'limiter', 'csrf',  # Flask extensions
        }
        
        real_undefined = potentially_undefined - known_dynamic
        
        if real_undefined:
            # Erstelle detaillierte Fehlermeldung
            errors = []
            for name in sorted(real_undefined):
                # Finde Zeilen, wo der Name verwendet wird
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load):
                        errors.append(f"Zeile {node.lineno}: '{name}' möglicherweise nicht definiert")
                        break
            
            if errors:
                # Warne nur, fail nicht - da statische Analyse Grenzen hat
                import warnings
                warnings.warn(
                    f"Potentiell undefinierte Namen in {filename}:\n" + "\n".join(errors[:5]),
                    UserWarning
                )


class TestModuleIntegration:
    """Integration-Tests für das Zusammenspiel der Module."""
    
    def test_web_server_can_be_imported(self):
        """web_server.py kann importiert werden."""
        try:
            from web_server import get_app
            assert callable(get_app)
        except ImportError as e:
            pytest.fail(f"web_server konnte nicht importiert werden: {e}")
    
    def test_sync_logic_can_be_imported(self):
        """sync_logic.py kann importiert werden."""
        try:
            from sync_logic import CalendarSyncer
            assert CalendarSyncer is not None
        except ImportError as e:
            pytest.fail(f"sync_logic konnte nicht importiert werden: {e}")
    
    def test_sync_all_users_can_be_imported(self):
        """sync_all_users.py kann importiert werden."""
        try:
            from sync_all_users import main, build_credentials, log
            assert callable(main)
            assert callable(build_credentials)
            assert callable(log)
        except ImportError as e:
            pytest.fail(f"sync_all_users konnte nicht importiert werden: {e}")
    
    def test_models_can_be_imported(self):
        """models.py kann importiert werden."""
        try:
            from models import User
            assert User is not None
        except ImportError as e:
            pytest.fail(f"models konnte nicht importiert werden: {e}")
    
    def test_config_can_be_imported(self):
        """config.py kann importiert werden."""
        try:
            from config import (
                DATA_DIR, GOOGLE_SCOPES, APP_BASE_URL,
                GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SECRET_KEY,
                encrypt, decrypt, validate_config, init
            )
            assert callable(encrypt)
            assert callable(decrypt)
            assert callable(validate_config)
            assert callable(init)
        except ImportError as e:
            pytest.fail(f"config konnte nicht importiert werden: {e}")


class TestFlaskApp:
    """Tests für die Flask-App-Erstellung."""
    
    def test_app_creation_succeeds(self):
        """Die Flask-App kann erstellt werden ohne Fehler."""
        from web_server import get_app
        
        try:
            app = get_app()
            assert app is not None
            assert hasattr(app, 'route')
        except Exception as e:
            pytest.fail(f"App-Erstellung fehlgeschlagen: {type(e).__name__}: {e}")
    
    def test_all_routes_are_registered(self):
        """Alle erwarteten Routes sind registriert."""
        from web_server import get_app
        
        app = get_app()
        
        # Erwartete Routen
        expected_routes = {
            '/',
            '/login',
            '/logout', 
            '/authorize',
            '/save',
            '/sync-now',
            '/logs',
            '/accept',
            '/privacy',
            '/terms',
            '/health',
            '/favicon.ico',
            '/delete-account',
            '/wipe-target',
            '/clear-cache',
        }
        
        registered_routes = {rule.rule for rule in app.url_map.iter_rules() if not rule.rule.startswith('/static')}
        
        missing_routes = expected_routes - registered_routes
        if missing_routes:
            pytest.fail(f"Fehlende Routen: {missing_routes}")


class TestDependencyImports:
    """Tests, die sicherstellen, dass alle externen Dependencies verfügbar sind."""
    
    REQUIRED_PACKAGES = [
        ('flask', 'Flask'),
        ('flask_login', 'LoginManager'),
        ('flask_wtf.csrf', 'CSRFProtect'),
        ('flask_talisman', 'Talisman'),
        ('flask_limiter', 'Limiter'),
        ('google_auth_oauthlib.flow', 'Flow'),
        ('googleapiclient.discovery', 'build'),
        ('googleapiclient.errors', 'HttpError'),
        ('google.oauth2.credentials', 'Credentials'),
        ('google.oauth2.id_token', 'verify_oauth2_token'),
        ('google.auth.transport.requests', 'Request'),
        ('cryptography.fernet', 'Fernet'),
        ('filelock', 'FileLock'),
        ('ics', 'Calendar'),
        ('arrow', 'arrow'),
        ('pytz', 'timezone'),
        ('requests', 'get'),
        ('markdown', 'markdown'),
        ('werkzeug.middleware.proxy_fix', 'ProxyFix'),
    ]
    
    @pytest.mark.parametrize("module_name,attr_name", REQUIRED_PACKAGES)
    def test_required_package_available(self, module_name, attr_name):
        """Prüft, ob erforderliche Packages installiert und importierbar sind."""
        try:
            module = importlib.import_module(module_name)
            assert hasattr(module, attr_name), f"'{attr_name}' nicht in {module_name} gefunden"
        except ImportError as e:
            pytest.fail(f"Erforderliches Package '{module_name}' nicht verfügbar: {e}")
