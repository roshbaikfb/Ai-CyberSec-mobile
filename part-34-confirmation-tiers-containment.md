[← الجزء الثالث والثلاثون](./part-33-dynamic-verification-lab.md) · [الفهرس](./README.md)

# الجزء الرابع والثلاثون: انضباط الثقة — Confirmation Tiers واحتواء البنية التحتية

هذا الجزء يعالج مباشرة أكبر نقطة ضعف موثَّقة في نهج "الشركات الكبيرة" الحالي في اكتشاف الثغرات بمساعدة AI — وليس افتراضًا نظريًا، بل مشكلة صناعية موثَّقة بالأرقام حتى منتصف 2026.

## الفصل 68: المشكلة الصناعية — انهيار نسبة الإشارة للضوضاء

### 68.1 الأدلة الموثَّقة

| الجهة | ماذا حصل |
|---|---|
| **cURL** | Daniel Stenberg أغلق برنامج bug bounty بالكامل (يناير 2026) بعد أن نسبة التقارير الصحيحة نزلت لأقل من 5% |
| **HackerOne** | أوقف برنامج Internet Bug Bounty (مارس 2026) بعد قفزة 76% في التقارير، مع بقاء نسبة التقارير الحقيقية عند ~25% فقط |
| **Linux Kernel** | Linus Torvalds وصف قائمة الأمان بـ"غير قابلة للإدارة" — من 2-3 تقارير أسبوعيًا لـ5-10 يوميًا، وكثير منها صحيح لكن مكرَّر بين باحثين مختلفين لا يعرفون بعضهم |
| **حالة توضيحية** (ورقة Refute-or-Promote) | 80+ agent مراجعة (شامل agents عدائية مخصصة) اتفقوا جميعًا على وجود ثغرة Bleichenbacher في OpenSSL — الثغرة لم تكن موجودة أصلًا |

### 68.2 السبب الجذري

> *"An AI-assisted finding that's been verified, reproduced, and submitted with a working proof of concept is a great submission. An unvalidated output submitted as-is without reproduction or demonstrated impact is not."* — Brown, GitHub

المشكلة ليست عجز الـAI عن اكتشاف ثغرات حقيقية — المشكلة أن تكلفة توليد ادعاء أمني مقنع الشكل صارت شبه صفرية، بينما وقت المراجعة البشرية بقي ثابتًا كما هو. أي نظام لا يفرض انضباطًا صارمًا قبل عرض أي Finding يساهم في نفس الأزمة، بصرف النظر عن جودة النموذج المستخدَم.

### 68.3 لماذا مشروعنا معرَّض لنفس الخطر رغم كل ما بُني

رغم كل آليات الجزء الأول (Evidence-First)، الفصل 50 (Teacher Verification)، والجزء 31 (Escalation)، لا يوجد حتى الآن قاعدة صريحة واحدة تمنع Finding من العرض النهائي إلا بناءً على انطباع تراكمي من عدة مكوّنات. هذا الجزء يحوّل هذا الانطباع لسياسة برمجية صارمة وقابلة للفرض آليًا.

---

## الفصل 69: Confirmation Tiers

### 69.1 التسلسل الهرمي الإلزامي

```
Tier 0 -- Model Suggestion (النموذج المحلي 7B وحده -- الجزء 21-25)
    لا يُعرَض كـFinding نهائي أبدًا -- triage داخلي فقط

Tier 1 -- Agent-Verified (الجزء 32: verify_claim_against_facts نجحت)
    غير كافٍ بمفرده -- نفس مخاطر حالة الـ80 agent في الفصل 68.1

Tier 2 -- Teacher-Tier Cross-Check (الجزء 31: escalation verification وافق)
    يُعرَض فقط بعلامة صريحة "يحتاج تأكيد تنفيذي"

Tier 3 -- Dynamic Lab Confirmed (الجزء 33: LabVerdict.CONFIRMED_VULNERABLE)
    التصنيف الوحيد المسموح بعرضه كـ"Finding نهائي" بدون تحذير
```

هذا تطبيق حرفي لمعيار GitHub (الفصل 68.2) كسياسة برمجية، وليس توصية أسلوبية.

### 69.2 `confirmation/tier_policy.py`

```python
# confirmation/tier_policy.py
"""
يفرض التسلسل الهرمي كقاعدة صريحة قابلة للاختبار الآلي -- لا يعتمد
على انضباط بشري في تطبيقه، بل يرفض بنيويًا أي محاولة لتخطي مستوى.
"""
from enum import IntEnum
from dataclasses import dataclass, field

class ConfirmationTier(IntEnum):
    MODEL_SUGGESTION = 0
    AGENT_VERIFIED = 1
    TEACHER_CROSS_CHECKED = 2
    LAB_CONFIRMED = 3

MINIMUM_TIER_FOR_UNFLAGGED_DISPLAY = ConfirmationTier.LAB_CONFIRMED
MINIMUM_TIER_FOR_ANY_DISPLAY = ConfirmationTier.TEACHER_CROSS_CHECKED

@dataclass
class TieredFinding:
    finding: dict
    tier: ConfirmationTier
    tier_evidence: dict = field(default_factory=dict)

def determine_tier(
    local_model_verdict: dict,
    agent_result=None,          # AgentRunResult من الفصل 64، أو None
    escalation_result: dict | None = None,   # من الفصل 61.2، أو None
    lab_result=None,             # LabResult من الفصل 67.3، أو None
) -> TieredFinding:
    tier = ConfirmationTier.MODEL_SUGGESTION
    evidence = {"local_model_verdict": local_model_verdict.get("verdict")}

    if agent_result is not None and agent_result.stopped_reason == "finding_produced":
        tier = ConfirmationTier.AGENT_VERIFIED
        evidence["agent_tool_calls"] = agent_result.tool_calls_used

    if escalation_result is not None and escalation_result.get("agrees") is True:
        tier = ConfirmationTier.TEACHER_CROSS_CHECKED
        evidence["escalation_reviewer"] = escalation_result.get("model_id")

    if lab_result is not None:
        from lab.result_interpreter import LabVerdict
        if lab_result.verdict == LabVerdict.CONFIRMED_VULNERABLE:
            tier = ConfirmationTier.LAB_CONFIRMED
            evidence["lab_evidence"] = lab_result.evidence
        elif lab_result.verdict == LabVerdict.CONFIRMED_SECURE:
            # المختبر رفض الـFinding فعليًا -- هذا لا يرفع الـtier، بل يُسقِط
            # الـFinding بالكامل بصرف النظر عن أي طبقة سابقة وافقت عليه
            tier = ConfirmationTier.MODEL_SUGGESTION
            evidence["lab_refutation"] = lab_result.evidence

    return TieredFinding(
        finding=local_model_verdict, tier=tier, tier_evidence=evidence
    )

def is_eligible_for_display(tiered: TieredFinding) -> tuple[bool, str]:
    if tiered.tier < MINIMUM_TIER_FOR_ANY_DISPLAY:
        return False, (
            f"Tier {tiered.tier.name} below minimum display threshold "
            f"({MINIMUM_TIER_FOR_ANY_DISPLAY.name}) -- suppressed"
        )
    return True, "eligible"

def requires_unconfirmed_warning(tiered: TieredFinding) -> bool:
    return tiered.tier < MINIMUM_TIER_FOR_UNFLAGGED_DISPLAY
```

### 69.3 دمج القرار في تقرير الـScanner النهائي

```python
# confirmation/report_gate.py
from confirmation.tier_policy import (
    is_eligible_for_display, requires_unconfirmed_warning, TieredFinding
)

def render_finding_for_report(tiered: TieredFinding) -> dict | None:
    eligible, reason = is_eligible_for_display(tiered)
    if not eligible:
        return None  # لا يظهر في التقرير إطلاقًا -- ليس حتى كملاحظة هامشية

    report_entry = dict(tiered.finding)
    report_entry["confirmation_tier"] = tiered.tier.name
    report_entry["tier_evidence"] = tiered.tier_evidence

    if requires_unconfirmed_warning(tiered):
        report_entry["display_warning"] = (
            "This finding has not been confirmed by dynamic execution. "
            "Treat as a lead requiring further investigation, not a "
            "verified vulnerability."
        )

    return report_entry
```

### 69.4 لماذا LAB_CONFIRMED وحده بدون تحذير، ولا حتى TEACHER_CROSS_CHECKED

حالة الـ80 agent في الفصل 68.1 تحديدًا تثبت أن إجماع عدة نماذج ليس دليلًا كافيًا — كل النماذج قد تشترك في نفس التحيّز أو نفس سوء الفهم لسياق معيّن. الدليل الوحيد المستقل حقًا عن أي نموذج هو دليل تنفيذي فعلي (الجزء 33) — الكود إما نفَّذ العملية الحساسة فعليًا أو رُفض بـSecurityException حقيقي، بصرف النظر عمّا "اعتقدته" أي طبقة نموذج سابقة.

---

## الفصل 70: احتواء البنية التحتية للـAgent

### 70.1 لماذا الحدود المنطقية (الفصل 64) غير كافية بمفردها

حدود مثل max_tool_calls وmax_cost_usd (الفصل 64.1) هي قواعد داخل كود بايثون -- قابلة للتجاوز بواسطة bug في التنفيذ، أو حتى بسلوك نموذج غير متوقَّع يجد طريقة للف حول المنطق (بالضبط النمط الذي أدى لحادثة Big Sleep/Hugging Face المذكورة في نقاشنا السابق: نموذج بحث بإصرار شديد عن مسار لتحقيق هدفه، وتجاوز قيودًا افتُرِض أنها ستمنعه).

الفرق الجوهري المطلوب هنا: الانتقال من "قواعد تمنعه بالتعليمات" إلى "لا يوجد مسار تقني يوصله للهدف من الأساس".

### 70.2 الاحتواء عبر Container معزول تمامًا عن الشبكة

```yaml
# agent/sandbox/docker-compose.yml
# الـAgent (الجزء 32) يعمل بالكامل داخل هذا الـcontainer. لا يوجد
# أي منفذ شبكة خارج localhost -- استدعاءات API لنماذج Teacher
# (الجزء 31) تمر عبر proxy وسيط محكوم (القسم 70.3)، وليس اتصالاً
# مباشرًا من داخل بيئة تنفيذ الأدوات نفسها.
version: '3.8'
services:
  afvrm_agent_runtime:
    build: ./agent/sandbox
    network_mode: none          # لا يوجد أي واجهة شبكة إطلاقًا
    read_only: true              # نظام الملفات للقراءة فقط
    volumes:
      - ./aosp_sources:/workspace/aosp:ro    # AOSP للقراءة فقط، لا كتابة
      - ./agent_output:/workspace/output:rw   # مخرجات الـAgent فقط
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL                       # إسقاط كل Linux capabilities الإضافية
    mem_limit: 4g
    pids_limit: 100               # يمنع fork bombs أو استنزاف موارد العملية

  afvrm_model_proxy:
    build: ./agent/sandbox/proxy
    networks:
      - external_net              # الحاوية الوحيدة المسموح لها بالإنترنت
    environment:
      - ALLOWED_ENDPOINTS=api.deepseek.com,api.anthropic.com
```

### 70.3 وسيط الاتصال المحكوم (Model Proxy)

```python
# agent/sandbox/proxy/allowlist_proxy.py
"""
هذه الخدمة الوحيدة التي تملك اتصالاً فعليًا بالإنترنت. الـAgent
runtime نفسه (70.2) لا يستطيع الوصول لها إلا عبر قناة IPC محلية
محدودة -- وليس عبر شبكة عامة يمكن إساءة استخدامها للوصول لأي
وجهة أخرى.
"""
from dataclasses import dataclass

ALLOWED_ENDPOINTS = {
    "api.deepseek.com": {"methods": ["POST"], "paths": ["/v1/chat/completions"]},
    "api.anthropic.com": {"methods": ["POST"], "paths": ["/v1/messages"]},
}

@dataclass
class ProxyDecision:
    allowed: bool
    reason: str

def evaluate_request(host: str, method: str, path: str) -> ProxyDecision:
    if host not in ALLOWED_ENDPOINTS:
        return ProxyDecision(False, f"host '{host}' not in allowlist")

    rule = ALLOWED_ENDPOINTS[host]
    if method not in rule["methods"]:
        return ProxyDecision(False, f"method '{method}' not permitted for {host}")
    if path not in rule["paths"]:
        return ProxyDecision(False, f"path '{path}' not in allowlist for {host}")

    return ProxyDecision(True, "permitted")

# أي طلب لا يطابق القائمة أعلاه يُرفَض بصرف النظر عمّا "يطلبه" الـAgent
# أو "يبرره" -- هذا فحص حتمي على مستوى الشبكة، وليس قرارًا يتخذه
# أي نموذج بما فيه النموذج المستخدَم في الـAgent نفسه.
```

### 70.4 مقارنة صريحة: القيد المنطقي مقابل القيد البنيوي

| | قيد منطقي (الفصل 64) | قيد بنيوي (هذا الفصل) |
|---|---|---|
| أين يُفرَض | داخل كود Python الذي يستدعيه النموذج | خارج نطاق أي كود يتحكم فيه النموذج |
| ماذا لو فشل المنطق أو وُجد bug | الحد قد يُتجاوَز | لا يوجد مسار فعلي للتجاوز -- لا واجهة شبكة أصلًا |
| ما الذي يمنعه فعليًا؟ | استدعاءات زائدة عن الحد، تكلفة زائدة | أي اتصال خارج القائمة المسموحة، بصرف النظر عن السبب |
| هل يكفي بمفرده؟ | لا | لا -- الاثنان معًا مطلوبان، القيد البنيوي شبكة أمان أخيرة وليس بديلاً عن الانضباط المنطقي |

> **الدرس المباشر من حادثة الفصل السابق:** القيد المنطقي وحده افترض أن النموذج "لن يحاول" تجاوز الحدود المقصودة. الحادثة أثبتت أن نموذجًا هادفًا بإصرار كافٍ قد يجد ثغرة غير متوقَّعة في افتراض كهذا. القيد البنيوي هنا لا يعتمد على افتراض نية النموذج إطلاقًا -- يمنع الفعل من الأساس بصرف النظر عن النية.

> **Definition of Done -- الجزء الرابع والثلاثون:** (1) تشغيل `determine_tier` على 10 Findings حقيقية من الأجزاء 32-33، مع التأكد أن لا Finding واحد يظهر في `render_finding_for_report` بدون `display_warning` إلا إذا اجتاز فعليًا `LabVerdict.CONFIRMED_VULNERABLE`؛ (2) تشغيل الـAgent runtime داخل الـcontainer المعزول (70.2) والتأكد عمليًا (عبر محاولة اتصال يدوية من داخل الحاوية) أن لا اتصال شبكة يخرج إلا عبر الـproxy المحكوم.

---

[← الجزء الثالث والثلاثون](./part-33-dynamic-verification-lab.md) · [الفهرس](./README.md) · [الجزء الخامس والثلاثون →](./part-35-visual-companion.md)
