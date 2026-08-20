[← الجزء الثامن](./part-08-security-bulletins.md) · [الفهرس](./README.md)

# الجزء التاسع: Parsing

## الفصل 19: Java/Kotlin Parsing

استخدمنا Tree-sitter بشكل مبسّط في الفصل 17 لاستخراج حدود method واحدة. هذا الفصل يبني Wrapper كامل وقابل لإعادة الاستخدام عبر باقي المشروع (خاصة الجزء العاشر: Static Analysis Layer).

### 19.1 لماذا Tree-sitter تحديدًا

| الخيار | الميزة | العيب |
|---|---|---|
| Regex | بسيط وسريع | هش جدًا أمام أي تعقيد بنيوي (nested braces, comments تحتوي كود، strings تحتوي `{`) |
| Javaparser (مكتبة Java مخصصة) | دقة عالية جدًا لـJava تحديدًا | يتطلب JVM، تعقيد إضافي في بيئة Python، لا يدعم Kotlin بنفس الأداة |
| **Tree-sitter** | سريع، incremental parsing، يدعم لغات متعددة بواجهة موحدة، لا يحتاج JVM | Grammar لبعض الحالات النادرة في Java الحديث قد يحتاج تحديث دوري |

القرار: Tree-sitter عبر `tree-sitter-languages` (مثبتة في الفصل 11) هو الخيار العملي الأنسب لبيئتنا.

### 19.2 `parser/java_parser.py` — الغلاف الأساسي

```python
# parser/java_parser.py
"""
غلاف موحّد حول tree-sitter لاستخراج: methods، classes، imports،
annotations، استدعاءات (calls)، معاملات، وأرقام الأسطر.
هذا هو المكوّن الذي سيستهلكه security_rules/ وcandidate_generator/
لاحقًا في الجزء العاشر.
"""
from dataclasses import dataclass, field
from tree_sitter_languages import get_parser

JAVA_PARSER = get_parser("java")

@dataclass
class MethodInfo:
    name: str
    start_line: int
    end_line: int
    parameters: list[tuple[str, str]]  # (type, name)
    annotations: list[str]
    modifiers: list[str]
    body_source: str
    calls: list[str] = field(default_factory=list)

@dataclass
class ClassInfo:
    name: str
    start_line: int
    end_line: int
    superclass: str | None
    implemented_interfaces: list[str]
    methods: list[MethodInfo] = field(default_factory=list)

@dataclass
class FileInfo:
    imports: list[str]
    classes: list[ClassInfo]

def _text(node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode("utf8", errors="replace")

def _extract_calls(method_node, source_bytes: bytes) -> list[str]:
    calls = []
    def walk(node):
        if node.type == "method_invocation":
            name_node = node.child_by_field_name("name")
            if name_node:
                calls.append(_text(name_node, source_bytes))
        for child in node.children:
            walk(child)
    walk(method_node)
    return calls

def _extract_parameters(method_node, source_bytes: bytes) -> list[tuple[str, str]]:
    params = []
    param_list = next(
        (c for c in method_node.children if c.type == "formal_parameters"), None
    )
    if not param_list:
        return params
    for child in param_list.children:
        if child.type == "formal_parameter":
            type_node = child.child_by_field_name("type")
            name_node = child.child_by_field_name("name")
            if type_node and name_node:
                params.append((_text(type_node, source_bytes), _text(name_node, source_bytes)))
    return params

def _extract_annotations_and_modifiers(method_node, source_bytes: bytes):
    annotations, modifiers = [], []
    for child in method_node.children:
        if child.type == "modifiers":
            for sub in child.children:
                if sub.type == "annotation" or sub.type == "marker_annotation":
                    annotations.append(_text(sub, source_bytes))
                elif sub.type in ("public", "private", "protected", "static", "final"):
                    modifiers.append(sub.type)
    return annotations, modifiers

def parse_method(method_node, source_bytes: bytes) -> MethodInfo:
    name_node = method_node.child_by_field_name("name")
    name = _text(name_node, source_bytes) if name_node else "unknown"
    annotations, modifiers = _extract_annotations_and_modifiers(method_node, source_bytes)

    return MethodInfo(
        name=name,
        start_line=method_node.start_point[0] + 1,
        end_line=method_node.end_point[0] + 1,
        parameters=_extract_parameters(method_node, source_bytes),
        annotations=annotations,
        modifiers=modifiers,
        body_source=_text(method_node, source_bytes),
        calls=_extract_calls(method_node, source_bytes),
    )

def parse_class(class_node, source_bytes: bytes) -> ClassInfo:
    name_node = class_node.child_by_field_name("name")
    superclass_node = class_node.child_by_field_name("superclass")
    interfaces_node = class_node.child_by_field_name("interfaces")

    methods = [
        parse_method(child, source_bytes)
        for child in class_node.children
        if child.type == "method_declaration"
    ]

    implemented = []
    if interfaces_node:
        implemented = [
            _text(n, source_bytes) for n in interfaces_node.children
            if n.type == "type_identifier"
        ]

    return ClassInfo(
        name=_text(name_node, source_bytes) if name_node else "unknown",
        start_line=class_node.start_point[0] + 1,
        end_line=class_node.end_point[0] + 1,
        superclass=_text(superclass_node, source_bytes) if superclass_node else None,
        implemented_interfaces=implemented,
        methods=methods,
    )

def parse_file(source: str) -> FileInfo:
    source_bytes = bytes(source, "utf8")
    tree = JAVA_PARSER.parse(source_bytes)
    root = tree.root_node

    imports = [
        _text(node, source_bytes).replace("import ", "").rstrip(";")
        for node in root.children if node.type == "import_declaration"
    ]

    classes = [
        parse_class(node, source_bytes)
        for node in root.children if node.type == "class_declaration"
    ]

    return FileInfo(imports=imports, classes=classes)
```

### 19.3 اختبار سريع

```python
# tests/test_java_parser.py
from parser.java_parser import parse_file

SAMPLE = """
package com.android.server;

import android.os.Binder;
import android.os.UserHandle;

public class FooService extends IFoo.Stub {
    @Override
    public void doSomething(int targetUserId, String packageName) {
        int callingUid = Binder.getCallingUid();
        enforceCrossUserPermission(callingUid, targetUserId);
        performOperation(targetUserId, packageName);
    }
}
"""

def test_parse_basic_class():
    result = parse_file(SAMPLE)
    assert len(result.classes) == 1
    cls = result.classes[0]
    assert cls.name == "FooService"
    assert cls.superclass is None or "IFoo" in (cls.superclass or "")
    assert len(cls.methods) == 1

    method = cls.methods[0]
    assert method.name == "doSomething"
    assert ("int", "targetUserId") in method.parameters
    assert "getCallingUid" in method.calls
    assert "enforceCrossUserPermission" in method.calls
```

تشغيل:

```bash
pytest tests/test_java_parser.py -v
```

> **Kotlin:** نفس المنطق يُكرَّر عبر `get_parser("kotlin")` مع تعديل أسماء أنواع الـnodes (تختلف قواعد Kotlin grammar عن Java — مثلًا `function_declaration` بدل `method_declaration`). نؤجل هذا لإصدار لاحق (v0.2) لأن الغالبية العظمى من `frameworks/base/services/core` مكتوبة بـJava.

---

## الفصل 20: Security API Extraction

بعد أن أصبح لدينا `MethodInfo.calls` (قائمة كل الاستدعاءات داخل method)، هذا الفصل يبني الطبقة التي تفلتر هذه القائمة لتحديد الاستدعاءات ذات **الأهمية الأمنية تحديدًا** — وهي المدخل المباشر لـSecurity Facts Extractor في الفصل 21.

### 20.1 القائمة القابلة للتهيئة (Configurable)

بدل ترميز القائمة داخل الكود، نضعها في ملف تهيئة منفصل — لأن هذه القائمة ستنمو بمرور الوقت مع اكتشاف أنماط جديدة.

```yaml
# security_rules/api_catalog.yaml
identity_apis:
  - Binder.getCallingUid
  - Binder.getCallingPid
  - Binder.clearCallingIdentity
  - Binder.restoreCallingIdentity
  - UserHandle.getCallingUserId
  - UserHandle.getAppId
  - UserHandle.getUserId

permission_apis:
  - checkCallingPermission
  - enforceCallingPermission
  - checkCallingOrSelfPermission
  - enforceCallingOrSelfPermission
  - checkComponentPermission
  - checkPermission
  - enforcePermission

cross_user_apis:
  - enforceCrossUserPermission
  - enforceCrossUserPermissionIfNeeded
  - handleIncomingUser

appops_apis:
  - AppOpsManager.noteOp
  - AppOpsManager.checkOp
  - AppOpsManager.checkOpNoThrow
  - AppOpsManager.noteOpNoThrow

package_apis:
  - PackageManager.getPackageUid
  - PackageManager.getPackagesForUid
  - AppOpsManager.checkPackage

intent_apis:
  - PendingIntent.getActivity
  - PendingIntent.getBroadcast
  - PendingIntent.getService
  - Intent.getStringExtra
  - Intent.getIntExtra
  - Intent.getParcelableExtra

activity_manager_apis:
  - ActivityManager.getCurrentUser
  - ActivityManagerInternal.getCurrentUserId
```

### 20.2 `security_rules/catalog_loader.py`

```python
# security_rules/catalog_loader.py
import yaml
from pathlib import Path
from dataclasses import dataclass

@dataclass
class SecurityApiCatalog:
    identity_apis: set[str]
    permission_apis: set[str]
    cross_user_apis: set[str]
    appops_apis: set[str]
    package_apis: set[str]
    intent_apis: set[str]
    activity_manager_apis: set[str]

    def category_of(self, call_name: str) -> str | None:
        """يرجع اسم الفئة إن كان call_name يطابق أحد الأسماء
        (مع مراعاة الأسماء المؤهَّلة بالكلاس مثل Binder.getCallingUid
        وغير المؤهَّلة مثل getCallingUid وحدها)."""
        short_name = call_name.split(".")[-1]
        for field_name in self.__dataclass_fields__:
            apis = getattr(self, field_name)
            for api in apis:
                api_short = api.split(".")[-1]
                if short_name == api_short:
                    return field_name
        return None

    def all_short_names(self) -> set[str]:
        names = set()
        for field_name in self.__dataclass_fields__:
            for api in getattr(self, field_name):
                names.add(api.split(".")[-1])
        return names

def load_catalog(path: Path = Path("security_rules/api_catalog.yaml")) -> SecurityApiCatalog:
    data = yaml.safe_load(path.read_text())
    return SecurityApiCatalog(
        identity_apis=set(data.get("identity_apis", [])),
        permission_apis=set(data.get("permission_apis", [])),
        cross_user_apis=set(data.get("cross_user_apis", [])),
        appops_apis=set(data.get("appops_apis", [])),
        package_apis=set(data.get("package_apis", [])),
        intent_apis=set(data.get("intent_apis", [])),
        activity_manager_apis=set(data.get("activity_manager_apis", [])),
    )
```

### 20.3 استخراج الاستدعاءات الأمنية من method محلَّلة

```python
# security_rules/api_extractor.py
from dataclasses import dataclass
from parser.java_parser import MethodInfo
from security_rules.catalog_loader import SecurityApiCatalog

@dataclass
class SecurityApiUsage:
    call_name: str
    category: str
    line_hint: int  # تقريبي — نستخدم start_line للـmethod ككل في v0.1

def extract_security_api_usages(
    method: MethodInfo, catalog: SecurityApiCatalog
) -> list[SecurityApiUsage]:
    usages = []
    for call in method.calls:
        category = catalog.category_of(call)
        if category:
            usages.append(SecurityApiUsage(
                call_name=call,
                category=category,
                line_hint=method.start_line,
            ))
    return usages

def summarize_method_security_profile(
    method: MethodInfo, catalog: SecurityApiCatalog
) -> dict:
    usages = extract_security_api_usages(method, catalog)
    categories_present = {u.category for u in usages}

    return {
        "method_name": method.name,
        "has_identity_ops": "identity_apis" in categories_present,
        "has_permission_check": "permission_apis" in categories_present,
        "has_cross_user_check": "cross_user_apis" in categories_present,
        "has_appops_check": "appops_apis" in categories_present,
        "has_package_check": "package_apis" in categories_present,
        "touches_intents": "intent_apis" in categories_present,
        "usages": [u.__dict__ for u in usages],
    }
```

### 20.4 مثال تشغيل كامل

```python
# مثال استخدام يربط الفصلين 19 و20 معًا
from parser.java_parser import parse_file
from security_rules.catalog_loader import load_catalog
from security_rules.api_extractor import summarize_method_security_profile

source = open("SomeService.java").read()
file_info = parse_file(source)
catalog = load_catalog()

for cls in file_info.classes:
    for method in cls.methods:
        profile = summarize_method_security_profile(method, catalog)
        if profile["has_identity_ops"] and not profile["has_cross_user_check"]:
            print(f"⚠ {cls.name}.{method.name}: يستخدم identity ops "
                  f"بدون cross-user check ظاهر — مرشّح لمراجعة (الفصل 22)")
```

هذا المثال الأخير هو بالضبط النمط الذي سيتحوّل في الفصل 22 (Candidate Generator) إلى قاعدة ترشيح رسمية — لكنه هنا يوضح كيف تتغذى مخرجات الفصل 20 مباشرة في المرحلة التالية.

> **Definition of Done — الجزء التاسع:** تشغيل `catalog_loader.py` + `api_extractor.py` على ملف حقيقي من `frameworks/base/services/core` (مثل جزء من `PackageManagerService.java`) ينتج قائمة `security_api_usages` غير فارغة، مع تصنيف صحيح يدويًا التحقق منه لعشر استدعاءات على الأقل.

---

[← الجزء الثامن](./part-08-security-bulletins.md) · [الفهرس](./README.md) · [الجزء العاشر →](./part-10-static-analysis.md)
