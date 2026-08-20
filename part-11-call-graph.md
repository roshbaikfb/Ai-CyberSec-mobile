[← الجزء العاشر](./part-10-static-analysis.md) · [الفهرس](./README.md)

# الجزء الحادي عشر: Call Graph

الـCandidates من الجزء العاشر تُقيَّم كل واحدة بمعزل عن الأخرى، بناءً على محتوى method واحدة فقط. لكن كما وضحنا في الفصل 1، الثغرة أحيانًا موزَّعة عبر عدة methods: التحقق في `methodA`، والعملية الحساسة في `helper()` المستدعاة من `methodB`. هذا الجزء يبني الأداة التي تجعل النموذج "يرى" هذا التوزّع.

## الفصل 23: Call Graph

### 23.1 لماذا MVP بسيط يكفي الآن

بناء Call Graph دقيق 100% لمشروع بحجم `frameworks/base` (يشمل reflection، dynamic dispatch، lambdas، interfaces متعددة التطبيق) يتطلب أدوات على مستوى compiler كامل. **هذا ليس هدف v0.1.** الهدف هنا أداة عملية (MVP) تربط الاستدعاءات المباشرة الواضحة — وهي تغطي الغالبية العظمى من الحالات المفيدة لمشروعنا.

### 23.2 القيود المعروفة (Limitations) — صراحةً

| القيد | الأثر | كيف نتعامل معه الآن |
|---|---|---|
| لا يحل Polymorphism/Dynamic dispatch | استدعاء عبر interface قد لا يُربَط بالتطبيق الفعلي الصحيح | نربط بكل التطبيقات المحتملة (over-approximation) بدل تفويت الرابط |
| لا يتتبع Lambdas/Method references | استدعاءات داخل `() -> {...}` قد تُفقَد | نقبل هذا النقص في v0.1؛ نادر نسبيًا في الكود المستهدف |
| لا يتبع استدعاءات عبر Binder لخدمة أخرى | `mOtherService.doX()` يُسجَّل كاستدعاء لكن دون الدخول لتعريف الخدمة الأخرى | هذا **مقصود** — عبور حدود Binder هو نفسه Trust Boundary (الفصل 7) يجب تحليله ككيان منفصل، وليس دمجًا شفافًا |
| لا يحل استدعاءات عبر متغيرات من نوع غير معروف بدقة | نعتمد على النوع الظاهر في التصريح فقط | مقبول لأن معظم الكود المستهدف مكتوب بأنواع صريحة (Java، ليس Kotlin مع type inference معقّد) |

### 23.3 `call_graph/builder.py`

```python
# call_graph/builder.py
"""
يبني Call Graph على مستوى الملف/الحزمة الواحدة (v0.1).
كل عقدة (node) هي (class_name, method_name).
كل حافة (edge) تعني: method A تستدعي method B (مباشرة، ظاهريًا في النص).
"""
from dataclasses import dataclass, field
from pathlib import Path
from parser.java_parser import parse_file, ClassInfo, MethodInfo

@dataclass
class CallGraphNode:
    class_name: str
    method_name: str
    file_path: str

@dataclass
class CallGraph:
    nodes: dict[str, CallGraphNode] = field(default_factory=dict)
    edges: dict[str, set[str]] = field(default_factory=dict)  # node_id -> {node_id, ...}
    reverse_edges: dict[str, set[str]] = field(default_factory=dict)

    def node_id(self, class_name: str, method_name: str) -> str:
        return f"{class_name}.{method_name}"

    def add_node(self, class_name: str, method_name: str, file_path: str):
        nid = self.node_id(class_name, method_name)
        if nid not in self.nodes:
            self.nodes[nid] = CallGraphNode(class_name, method_name, file_path)
            self.edges[nid] = set()
            self.reverse_edges[nid] = set()

    def add_edge(self, caller_id: str, callee_id: str):
        self.edges.setdefault(caller_id, set()).add(callee_id)
        self.reverse_edges.setdefault(callee_id, set()).add(caller_id)

    def callees_of(self, node_id: str) -> set[str]:
        return self.edges.get(node_id, set())

    def callers_of(self, node_id: str) -> set[str]:
        return self.reverse_edges.get(node_id, set())

def build_call_graph_for_directory(dir_path: Path) -> CallGraph:
    graph = CallGraph()

    # الخطوة 1: تسجيل كل method كـnode أولًا (حتى نعرف كل الأسماء الممكنة)
    method_index: dict[str, list[str]] = {}  # method_short_name -> [node_ids]
    file_class_methods: list[tuple[str, ClassInfo, MethodInfo]] = []

    for java_file in dir_path.rglob("*.java"):
        try:
            source = java_file.read_text(errors="replace")
            file_info = parse_file(source)
        except Exception as e:
            print(f"parse failed for {java_file}: {e}")
            continue

        for cls in file_info.classes:
            for method in cls.methods:
                graph.add_node(cls.name, method.name, str(java_file))
                nid = graph.node_id(cls.name, method.name)
                method_index.setdefault(method.name, []).append(nid)
                file_class_methods.append((str(java_file), cls, method))

    # الخطوة 2: بناء الحواف — لكل استدعاء داخل method، نربطه بكل node
    # يحمل نفس الاسم (over-approximation بسبب غياب type resolution دقيق)
    for file_path, cls, method in file_class_methods:
        caller_id = graph.node_id(cls.name, method.name)
        for call_name in method.calls:
            matches = method_index.get(call_name, [])
            for callee_id in matches:
                if callee_id != caller_id:  # تجاهل self-recursion في v0.1 للتبسيط
                    graph.add_edge(caller_id, callee_id)

    return graph
```

### 23.4 استعلامات مفيدة فوق الـGraph

```python
# call_graph/queries.py
from call_graph.builder import CallGraph

def find_path_to_sink(graph: CallGraph, start_node: str, sink_keyword: str,
                       max_depth: int = 4) -> list[str] | None:
    """بحث BFS بسيط لإيجاد مسار من entry point لأول method
    يحتوي اسمها على sink_keyword، ضمن عمق محدود."""
    from collections import deque

    visited = {start_node}
    queue = deque([(start_node, [start_node])])

    while queue:
        current, path = queue.popleft()
        if len(path) > max_depth:
            continue
        if sink_keyword.lower() in current.lower():
            return path
        for callee in graph.callees_of(current):
            if callee not in visited:
                visited.add(callee)
                queue.append((callee, path + [callee]))
    return None

def get_security_relevant_neighborhood(
    graph: CallGraph, node_id: str, depth: int = 1
) -> dict:
    """يرجع callers وcallees ضمن عمق محدود — هذا بالضبط ما سيُستخدم
    في الفصل 26 لبناء context محدود بدل إغراق النموذج بالملف كاملاً."""
    callers = set()
    callees = set()

    frontier = {node_id}
    for _ in range(depth):
        new_callers = set()
        new_callees = set()
        for n in frontier:
            new_callers |= graph.callers_of(n)
            new_callees |= graph.callees_of(n)
        callers |= new_callers
        callees |= new_callees
        frontier = new_callers | new_callees

    return {"callers": callers, "callees": callees}
```

> **Definition of Done — الفصل 23:** بناء الـgraph على مجلد حقيقي (مثل `pm/`) ينتج عدد nodes وedges منطقي (ليس صفرًا، وليس عددًا يفوق عدد methods الفعلي بشكل غير معقول)، مع تحقق يدوي أن `callees_of()` لعشر methods معروفة يعطي نتائج صحيحة فعليًا موجودة في الكود.

---

## الفصل 24: Multi-Function Security Reasoning

الآن بعد أن أصبح لدينا Call Graph، هذا الفصل يحدد **كيف** نستخدمه لبناء سياق تحليل متعدد الدوال — دون إغراق النموذج بملف كامل.

### 24.1 المكوّنات المطلوبة لسياق واحد

عند تحليل Candidate واحد (من الفصل 22)، السياق المثالي يحتوي:

```
Binder entry point (الـmethod المُرشَّحة نفسها)
   +
Helper methods المستدعاة مباشرة منها (عمق 1)
   +
أي Security helper مذكور بالاسم لكن تعريفه غير مرئي بعد (يُجلَب عبر Retriever — الفصل 25)
   +
الـSink المحدَّد (إن كان method منفصلة قابلة للجلب)
   +
Caller الفعلي إن وُجد (من الـreverse edges) — مفيد لمعرفة هل التحقق يحدث قبل الوصول لهذه الـmethod
```

### 24.2 لماذا لا نضع 20,000 سطر عشوائيًا

- **التكلفة:** كل سطر إضافي في الـcontext يقلل تركيز النموذج على الجزء ذي الصلة الفعلية.
- **الدقة:** إغراق النموذج بكود غير مرتبط يزيد احتمال أن يبني استنتاجًا على تفصيل عشوائي بعيد الصلة.
- **البديل:** نستخدم الـCall Graph لتحديد **بالضبط** أي methods ذات صلة، ثم الـRetriever (الفصل 25) لجلب تعريفاتها فقط.

### 24.3 `multi_function/context_assembler.py`

```python
# multi_function/context_assembler.py
"""
يجمّع كل المعلومات ذات الصلة بـCandidate واحد استعدادًا لبناء
الـprompt النهائي في الفصل 26. لا يبني الـprompt نفسه هنا —
فقط يحدد "ماذا نحتاج" كخطوة منفصلة عن "كيف نصيغه".
"""
from dataclasses import dataclass
from call_graph.builder import CallGraph
from call_graph.queries import get_security_relevant_neighborhood

@dataclass
class MultiFunctionContext:
    candidate_node_id: str
    candidate_source: str
    direct_callees: list[str]        # أسماء methods يجب جلب تعريفها
    direct_callers: list[str]        # من استدعى هذه الـmethod (إن أمكن تحديده)
    unresolved_security_calls: list[str]  # استدعاءات لأسماء تبدو أمنية
                                           # لكن تعريفها غير موجود بالـgraph الحالي
                                           # (على الأرجح في ملف/حزمة أخرى)

def identify_unresolved_security_calls(
    method_calls: list[str], known_method_names: set[str]
) -> list[str]:
    SECURITY_NAME_HINTS = [
        "enforce", "check", "validate", "verify", "authoriz", "permission",
    ]
    unresolved = []
    for call in method_calls:
        looks_security_related = any(
            hint in call.lower() for hint in SECURITY_NAME_HINTS
        )
        if looks_security_related and call not in known_method_names:
            unresolved.append(call)
    return unresolved

def assemble_context(
    graph: CallGraph,
    candidate_node_id: str,
    candidate_source: str,
    method_calls: list[str],
) -> MultiFunctionContext:
    neighborhood = get_security_relevant_neighborhood(graph, candidate_node_id, depth=1)
    known_names = {nid.split(".")[-1] for nid in graph.nodes}

    return MultiFunctionContext(
        candidate_node_id=candidate_node_id,
        candidate_source=candidate_source,
        direct_callees=sorted(neighborhood["callees"]),
        direct_callers=sorted(neighborhood["callers"]),
        unresolved_security_calls=identify_unresolved_security_calls(
            method_calls, known_names
        ),
    )
```

### 24.4 مثال ناتج

```python
ctx = assemble_context(
    graph=my_graph,
    candidate_node_id="FooService.updateUserSetting",
    candidate_source="<source code here>",
    method_calls=["getCallingUid", "checkCaller", "clearCallingIdentity",
                  "write", "restoreCallingIdentity"],
)

print(ctx.unresolved_security_calls)
# -> ['checkCaller']
# هذا بالضبط الإشارة التي تخبرنا: يجب جلب تعريف checkCaller عبر
# الـRetriever (الفصل 25) قبل أن يستطيع النموذج إصدار حكم نهائي
# بدل insufficient_context بسبب غياب معلومة كان يمكن توفيرها.
```

هذا الربط — بين ما هو "غير محلول" في الـCall Graph المحلي وما يحتاج **Retrieval** فعلي — هو بالضبط الجسر إلى الجزء الثاني عشر القادم.

> **Definition of Done — الجزء الحادي عشر:** لعشرة Candidates حقيقية من الجزء العاشر، تشغيل `assemble_context` ينتج `unresolved_security_calls` منطقية (تطابق فعليًا استدعاءات موجودة في الكود ولم تُعرَّف داخل نفس الملف/المجلد)، مع تأكيد يدوي أن القائمة لا تفوّت استدعاءً أمنيًا واضحًا ولا تُدرِج استدعاءً غير أمني بالخطأ.

---

[← الجزء العاشر](./part-10-static-analysis.md) · [الفهرس](./README.md) · [الجزء الثاني عشر →](./part-12-retrieval.md)
