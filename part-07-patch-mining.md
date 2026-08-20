[← الجزء السادس](./part-06-aosp-collection.md) · [الفهرس](./README.md)

# الجزء السابع: Security Patch Mining

هذا الجزء هو قلب جمع البيانات. الهدف: تحويل تاريخ Git الخام لـ`frameworks/base` إلى قائمة commits مرشَّحة بقوة لكونها security fixes، ثم استخراج before/after لكل واحدة بشكل قابل للاستخدام في توليد Samples لاحقًا (الفصل 29).

## الفصل 15: Git History Mining

### 15.1 ما الذي نحتاج استخراجه من كل commit

- رسالة الـcommit كاملة.
- الملفات المعدَّلة.
- الـdiff الكامل لكل ملف.
- الـparent commit (للمقارنة before/after).
- التاريخ.
- المؤلف (سياقي فقط — لا نستخدمه في قرارات الأمان).

### 15.2 `patch_miner/history_miner.py`

```python
# patch_miner/history_miner.py
"""
يمشي عبر تاريخ Git لمستودع محلي، ويستخرج لكل commit:
- الرسالة، الملفات المعدَّلة، الـparent، الطابع الزمني.
لا يحكم بعد ما إذا كانت security-relevant — هذا دور candidate_scorer.py
في الفصل 16. هذه الطبقة مسؤولة فقط عن الاستخراج الخام الشامل.
"""
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
import json

@dataclass
class RawCommit:
    commit_hash: str
    parent_hash: str
    author_date: str
    subject: str
    body: str
    changed_files: list[str]

def run(cmd: list[str], cwd: Path) -> str:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=True
    ).stdout

SEP = "\x1e"  # record separator غير قابل للتصادم مع نص الرسائل
FIELD_SEP = "\x1f"

def iter_commits(repo_path: Path, since: str | None = None,
                  until: str | None = None, path_filter: str | None = None):
    log_format = f"%H{FIELD_SEP}%P{FIELD_SEP}%aI{FIELD_SEP}%s{FIELD_SEP}%b{SEP}"
    cmd = ["git", "log", f"--pretty=format:{log_format}"]
    if since:
        cmd.append(f"--since={since}")
    if until:
        cmd.append(f"--until={until}")
    if path_filter:
        cmd += ["--", path_filter]

    raw = run(cmd, cwd=repo_path)
    records = [r for r in raw.split(SEP) if r.strip()]

    for record in records:
        parts = record.strip().split(FIELD_SEP)
        if len(parts) < 5:
            continue
        commit_hash, parents, date, subject, body = parts[:5]
        parent_hash = parents.split(" ")[0] if parents else ""

        changed = run(
            ["git", "diff-tree", "--no-commit-id", "--name-only",
             "-r", commit_hash],
            cwd=repo_path
        ).strip().splitlines()

        yield RawCommit(
            commit_hash=commit_hash,
            parent_hash=parent_hash,
            author_date=date,
            subject=subject,
            body=body,
            changed_files=changed,
        )

def mine_repository(repo_path: Path, output_path: Path,
                     path_filter: str = "services/core/java/com/android/server"):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w") as f:
        for commit in iter_commits(repo_path, path_filter=path_filter):
            f.write(json.dumps(asdict(commit), ensure_ascii=False) + "\n")
            count += 1
            if count % 500 == 0:
                print(f"...{count} commits mined")
    print(f"Total: {count} commits written to {output_path}")

if __name__ == "__main__":
    mine_repository(
        repo_path=Path("aosp_sources/android-14"),
        output_path=Path("patch_miner/output/android-14_raw_commits.jsonl"),
    )
```

> **ملاحظة أداء:** استدعاء `git diff-tree` لكل commit على حدة مكلف على تاريخ يمتد لآلاف الـcommits. لدفعات كبيرة، فكّر لاحقًا في استخدام `git log --name-only` دفعة واحدة وتحليل الناتج بدل استدعاء منفصل لكل commit — لكن نُبقي النسخة الأبسط هنا لوضوح المنطق في مرحلة MVP.

---

## الفصل 16: Candidate Security Commit Detection

هذا هو المكوّن الأهم في الجزء السابع. **لا نعتمد على كلمة "security" فقط** — هذا يفوّت غالبية الإصلاحات الأمنية الحقيقية التي تُوصف في رسائل الـcommit بمصطلحات تقنية محايدة (enforce, validate, permission, uid...).

### 16.1 نظام التسجيل (Scoring System)

كل commit يُسجَّل بناءً على عدة مؤشرات مستقلة، وليس بناءً على كلمة مفتاحية واحدة:

| الفئة | الأوزان تُجمع من | مثال |
|---|---|---|
| Commit message keywords | كلمات في الرسالة (`enforce`, `validate`, `permission`, `uid`, `cross-user`, `privilege`, `identity`, `AppOps`...) | "Enforce permission check before..." |
| Security Bulletin reference | ذكر صريح لـCVE أو ASB (Android Security Bulletin) | "Fixes CVE-2023-xxxxx" |
| Security-relevant API touch | الـdiff يلمس APIs من قائمة `security_rules/` (الفصل 20) | إضافة سطر يستدعي `enforceCallingPermission` |
| Code shape signals | نمط الـdiff نفسه (إضافة شرط `if` جديد قبل استدعاء حساس) | إضافة early-return قبل عملية موجودة |

> **تنبيه أساسي:** الـscore هنا Candidate Generation فقط — لا يعني أبدًا أن الـcommit فعلًا security fix. القرار النهائي يحدث لاحقًا عبر مراجعة (بشرية أو LLM موثَّق) في الفصل 30/31.

### 16.2 `patch_miner/candidate_scorer.py`

```python
# patch_miner/candidate_scorer.py
import json
import re
from pathlib import Path
from dataclasses import dataclass, asdict

MESSAGE_KEYWORDS = {
    "high": [
        "cve-", "security patch", "security fix", "privilege escalation",
        "unauthorized", "bypass",
    ],
    "medium": [
        "enforce", "permission", "cross-user", "crossuser", "uid",
        "identity", "appops", "authoriz", "validate", "sanitiz",
    ],
    "low": [
        "check", "verify", "restrict", "guard", "protect",
    ],
}

SECURITY_API_PATTERNS = [
    r"enforceCallingPermission",
    r"checkCallingPermission",
    r"enforceCallingOrSelfPermission",
    r"clearCallingIdentity",
    r"restoreCallingIdentity",
    r"getCallingUid",
    r"AppOpsManager",
    r"enforceCrossUserPermission",
    r"UserHandle\.getCallingUserId",
    r"PendingIntent",
]

@dataclass
class ScoredCommit:
    commit_hash: str
    subject: str
    score: float
    signals: list[str]

def score_message(subject: str, body: str) -> tuple[float, list[str]]:
    text = f"{subject}\n{body}".lower()
    score = 0.0
    signals = []
    for word in MESSAGE_KEYWORDS["high"]:
        if word in text:
            score += 3.0
            signals.append(f"message:high:{word}")
    for word in MESSAGE_KEYWORDS["medium"]:
        if word in text:
            score += 1.5
            signals.append(f"message:medium:{word}")
    for word in MESSAGE_KEYWORDS["low"]:
        if word in text:
            score += 0.5
            signals.append(f"message:low:{word}")
    return score, signals

def score_diff_content(diff_text: str) -> tuple[float, list[str]]:
    score = 0.0
    signals = []
    added_lines = [
        line for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    added_text = "\n".join(added_lines)

    for pattern in SECURITY_API_PATTERNS:
        matches = re.findall(pattern, added_text)
        if matches:
            score += 2.0 * len(matches)
            signals.append(f"api:{pattern}:{len(matches)}")

    # إشارة إضافية: إضافة شرط جديد (if/return) قرب استدعاء حساس
    if re.search(r"\+\s*if\s*\(.*(uid|user|permission|caller)", added_text, re.I):
        score += 1.0
        signals.append("shape:new_conditional_near_identity")

    return score, signals

def score_commit(commit: dict, diff_text: str) -> ScoredCommit:
    msg_score, msg_signals = score_message(
        commit["subject"], commit["body"]
    )
    diff_score, diff_signals = score_diff_content(diff_text)

    total = msg_score + diff_score
    return ScoredCommit(
        commit_hash=commit["commit_hash"],
        subject=commit["subject"],
        score=round(total, 2),
        signals=msg_signals + diff_signals,
    )

def get_diff(repo_path: Path, commit_hash: str, parent_hash: str) -> str:
    import subprocess
    return subprocess.run(
        ["git", "diff", parent_hash, commit_hash, "--",
         "services/core/java/com/android/server"],
        cwd=repo_path, capture_output=True, text=True
    ).stdout

def process_all(repo_path: Path, commits_jsonl: Path, output_path: Path,
                 min_score: float = 2.0):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    kept = 0
    total = 0
    with commits_jsonl.open() as fin, output_path.open("w") as fout:
        for line in fin:
            commit = json.loads(line)
            total += 1
            if not commit["parent_hash"]:
                continue
            diff_text = get_diff(
                repo_path, commit["commit_hash"], commit["parent_hash"]
            )
            scored = score_commit(commit, diff_text)
            if scored.score >= min_score:
                fout.write(json.dumps(asdict(scored), ensure_ascii=False) + "\n")
                kept += 1
            if total % 500 == 0:
                print(f"...{total} processed, {kept} candidates kept")
    print(f"Done: {kept}/{total} commits kept as candidates "
          f"(threshold={min_score})")

if __name__ == "__main__":
    process_all(
        repo_path=Path("aosp_sources/android-14"),
        commits_jsonl=Path("patch_miner/output/android-14_raw_commits.jsonl"),
        output_path=Path("patch_miner/output/android-14_candidates.jsonl"),
    )
```

> **ضبط `min_score`:** ابدأ بقيمة منخفضة نسبيًا (مثل 2.0) لتفضيل Recall على Precision في هذه المرحلة — الهدف هنا **تقليل الفرصة المفوَّتة**، وليس دقة نهائية. الفلترة الدقيقة تحدث لاحقًا في مراحل المراجعة والـQuality Scoring (الفصل 51).

---

## الفصل 17: Before/After Extraction

بعد ترشيح الـcommits، نحتاج استخراج نسخة الـmethod **قبل** التعديل و**بعده** بدقة — وليس الملف كاملًا، لأن الـmethod المحدَّدة هي وحدة العمل الأساسية للـDataset.

### 17.1 التحدي

الـdiff الخام (`git diff`) يعطي أسطرًا مضافة/محذوفة، لكن لا يحدد تلقائيًا:
- ما هي الـmethod الكاملة (بحدودها من `{` إلى `}`) التي تحتوي التغيير؟
- ما السياق المحيط (الـclass، الـimports ذات الصلة)؟

لهذا نحتاج AST-aware extraction بدل الاكتفاء بأسطر الـdiff الخام.

### 17.2 `patch_miner/before_after_extractor.py`

هذا السكريبت يستخدم إحداثيات الأسطر من الـdiff لتحديد أي method تأثرت، ثم يستخدم Tree-sitter (سنُثبّته ونستخدمه بالتفصيل في الفصل 19) لاستخراج حدود الـmethod كاملة من كلتا النسختين.

```python
# patch_miner/before_after_extractor.py
"""
يعتمد على tree_sitter_languages (مثبتة في الفصل 11).
لهذا الفصل نكتفي بواجهة مبسّطة؛ التفاصيل الكاملة لـparsing
تُشرح في الفصل 19 (Java/Kotlin Parsing).
"""
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
import json
import re

from tree_sitter_languages import get_parser

JAVA_PARSER = get_parser("java")

@dataclass
class MethodSnapshot:
    method_signature: str
    start_line: int
    end_line: int
    source_code: str

@dataclass
class BeforeAfterPair:
    commit_hash: str
    parent_hash: str
    file_path: str
    before: MethodSnapshot | None
    after: MethodSnapshot | None
    diff_snippet: str

def get_file_at_ref(repo_path: Path, ref: str, file_path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{file_path}"],
        cwd=repo_path, capture_output=True, text=True
    )
    return result.stdout if result.returncode == 0 else None

def find_changed_line_numbers(diff_text: str) -> list[int]:
    """يستخرج أرقام الأسطر المتأثرة من hunk headers مثل @@ -10,5 +10,7 @@"""
    lines = []
    for match in re.finditer(r"@@ -\d+,?\d* \+(\d+),?(\d*) @@", diff_text):
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) else 1
        lines.extend(range(start, start + max(count, 1)))
    return lines

def extract_enclosing_method(source: str, target_line: int) -> MethodSnapshot | None:
    """يبحث عن أقرب method_declaration يحتوي target_line."""
    tree = JAVA_PARSER.parse(bytes(source, "utf8"))

    def walk(node):
        if node.type == "method_declaration":
            start = node.start_point[0] + 1  # tree-sitter 0-indexed
            end = node.end_point[0] + 1
            if start <= target_line <= end:
                sig_node = next(
                    (c for c in node.children if c.type == "identifier"), None
                )
                signature = sig_node.text.decode() if sig_node else "unknown"
                return MethodSnapshot(
                    method_signature=signature,
                    start_line=start,
                    end_line=end,
                    source_code=source[node.start_byte:node.end_byte],
                )
        for child in node.children:
            result = walk(child)
            if result:
                return result
        return None

    return walk(tree.root_node)

def extract_pair(repo_path: Path, commit_hash: str, parent_hash: str,
                  file_path: str) -> BeforeAfterPair | None:
    diff_text = subprocess.run(
        ["git", "diff", parent_hash, commit_hash, "--", file_path],
        cwd=repo_path, capture_output=True, text=True
    ).stdout

    changed_lines = find_changed_line_numbers(diff_text)
    if not changed_lines:
        return None
    anchor_line = changed_lines[len(changed_lines) // 2]

    before_source = get_file_at_ref(repo_path, parent_hash, file_path)
    after_source = get_file_at_ref(repo_path, commit_hash, file_path)
    if before_source is None or after_source is None:
        return None

    before_method = extract_enclosing_method(before_source, anchor_line)
    after_method = extract_enclosing_method(after_source, anchor_line)

    return BeforeAfterPair(
        commit_hash=commit_hash,
        parent_hash=parent_hash,
        file_path=file_path,
        before=before_method,
        after=after_method,
        diff_snippet=diff_text[:4000],  # حد أقصى للحجم
    )

def process_candidates(repo_path: Path, candidates_jsonl: Path,
                        raw_commits_jsonl: Path, output_path: Path):
    # نحتاج changed_files من raw_commits، لذلك نبني فهرسًا سريعًا أولًا
    commit_files = {}
    with raw_commits_jsonl.open() as f:
        for line in f:
            c = json.loads(line)
            commit_files[c["commit_hash"]] = c

    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with candidates_jsonl.open() as fin, output_path.open("w") as fout:
        for line in fin:
            candidate = json.loads(line)
            full = commit_files.get(candidate["commit_hash"])
            if not full:
                continue
            for file_path in full["changed_files"]:
                if not file_path.endswith((".java", ".kt")):
                    continue
                pair = extract_pair(
                    repo_path, full["commit_hash"],
                    full["parent_hash"], file_path
                )
                if pair and pair.before and pair.after:
                    fout.write(
                        json.dumps(asdict(pair), ensure_ascii=False) + "\n"
                    )
                    written += 1
    print(f"Wrote {written} before/after pairs to {output_path}")

if __name__ == "__main__":
    process_candidates(
        repo_path=Path("aosp_sources/android-14"),
        candidates_jsonl=Path("patch_miner/output/android-14_candidates.jsonl"),
        raw_commits_jsonl=Path("patch_miner/output/android-14_raw_commits.jsonl"),
        output_path=Path("patch_miner/output/android-14_before_after.jsonl"),
    )
```

### 17.3 حالات خاصة يجب توقّعها

| الحالة | ماذا يحدث | كيف نتعامل معها |
|---|---|---|
| Method جديدة بالكامل (لا يوجد "before") | `before_method` سيكون `None` | نحتفظ بها كـsample من نوع "newly added security check" وليس before/after pair تقليدي |
| Method محذوفة بالكامل | `after_method` سيكون `None` | نادر، عادة إعادة هيكلة — نُهمله في v0.1 |
| التغيير يمتد لأكثر من method واحدة | `anchor_line` قد يقع في منطقة غير دقيقة | نقبل الخطأ في هذه المرحلة؛ الفصل 24 (Multi-Function Security Reasoning) سيتعامل مع هذا بشكل صريح لاحقًا |
| ملفات غير Java/Kotlin (مثل `.aidl`) | غير مدعومة بواسطة `JAVA_PARSER` | تُستبعد الآن، ونضيف parser مخصص لـAIDL إن استدعت الحاجة لاحقًا |

> **Definition of Done — الجزء السابع:** يوجد ملف `*_before_after.jsonl` يحتوي على الأقل 50 زوجًا صالحًا (both `before` و`after` غير فارغين) من إصدار واحد على الأقل، مع مراجعة يدوية سريعة لعشر حالات عشوائية للتأكد أن حدود الـmethod المستخرجة صحيحة فعليًا وليست جزءًا مبتورًا.

---

[← الجزء السادس](./part-06-aosp-collection.md) · [الفهرس](./README.md) · [الجزء الثامن →](./part-08-security-bulletins.md)
