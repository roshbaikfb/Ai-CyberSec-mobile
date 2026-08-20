[← الجزء الثاني والثلاثون](./part-32-agent-architecture.md) · [الفهرس](./README.md)

# الجزء الثالث والثلاثون: مختبر التحقق الديناميكي (Dynamic Verification Lab)

هذا هو v2 المؤجَّل من الفصل 64.3 -- طبقة تحقق تنفيذي فعلي فوق النتائج الثابتة (Static + Agent) من الأجزاء 10-32. **نطاق العمل هنا محصور بالكامل في AOSP على Emulator محلي** -- لا يوجد أي اتصال بأنظمة خارجية أو مواقع إنتاجية، والعزل هنا هدف يُحافَظ عليه، وليس عقبة يُتجاوَزها.

## الفصل 65: تصميم المختبر

### 65.1 لماذا Emulator وليس جهاز فعلي

| الخيار | الميزة | القرار |
|---|---|---|
| جهاز Android فعلي مروَّق (rooted) | يعكس بيئة حقيقية 100% | مخاطر أعلى، صعوبة استعادة حالة نظيفة بعد كل اختبار |
| **Android Emulator (AVD) -- userdebug build** | حالة نظيفة قابلة لإعادة الإنشاء فوريًا (snapshot/restore)، صلاحيات debug تسمح بمراقبة أعمق | الخيار المُتَّخذ |

### 65.2 بنية المختبر الكاملة

```
Candidate (من الجزء العاشر) + Finding (من الـAgent -- الجزء 32)
        |
        v
Test App Generator  --  يبني تطبيق APK صغير مخصص لهذا الـCandidate تحديدًا
        |
        v
AVD Snapshot (نظيف)  --  حالة معروفة، تُستعاد قبل كل اختبار
        |
        v
Install + Launch  --  عبر ADB، بهوية UID محددة (تحاكي المتصل المُفتَرَض)
        |
        v
Frida Hooks  --  مراقبة استدعاءات الـmethod المستهدفة أثناء التنفيذ الفعلي
        |
        v
Result Interpreter  --  هل التحقق نُفِّذ فعليًا؟ هل العملية الحساسة تمّت أم رُفضت؟
        |
        v
Lab Verdict  --  confirmed / refuted / inconclusive (يُضاف لـGround Truth -- الفصل 39)
```

### 65.3 إعداد البيئة الأساسية

```bash
# تثبيت أدوات AVD (تُضاف لما ثُبِّت في الفصل 11)
sudo apt install -y android-sdk-platform-tools

# تحميل Android SDK command-line tools
mkdir -p ~/android-sdk/cmdline-tools
cd ~/android-sdk/cmdline-tools
# نزّل الأداة من developer.android.com/studio#command-tools ثم فك الضغط هنا كـ 'latest'

export ANDROID_HOME=~/android-sdk
export PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools

# تثبيت صورة نظام userdebug (وليس user العادية -- تسمح بصلاحيات root/debug)
sdkmanager "system-images;android-14;google_apis_playstore;x86_64"
avdmanager create avd -n afvrm_lab -k "system-images;android-14;google_apis_playstore;x86_64"

# تثبيت Frida (للـhooking الديناميكي)
pip install frida-tools --break-system-packages
```

> **ملاحظة على userdebug مقابل الصور القياسية:** صور `google_apis_playstore` القياسية على Play Store محدودة الصلاحيات (production-like). للحصول على صلاحيات `su` وaccess أعمق لمراقبة `system_server`، الخيار الأدق هو بناء AOSP نفسه بصيغة `userdebug` (`lunch aosp_x86_64-userdebug && make`) -- عملية أطول لكنها تعطي تطابقًا كاملاً مع الكود اللي حللناه في الأجزاء السابقة. نبدأ بصورة `google_apis` الجاهزة في v0.1 للتبسيط، وننتقل لبناء AOSP الكامل لو احتجنا صلاحيات أعمق.

---

## الفصل 66: توليد تطبيق الاختبار تلقائيًا

### 66.1 لماذا التوليد آلي وليس يدوي

كل Candidate له معاملات مختلفة (targetUserId، packageName، إلخ) وهوية استدعاء مختلفة. توليد تطبيق اختبار يدوي لكل Candidate غير عملي على نطاق عشرات الحالات -- نحتاج قالبًا (template) يُملأ آليًا من بيانات الـFinding.

```python
# lab/test_app_generator.py
"""
يبني مشروع APK بسيط (Kotlin/Java) يستدعي الـmethod المستهدفة عبر
Binder بنفس التوقيع بالضبط، بمعاملات مُشتقة من الـFinding.
لا نكتب exploit كامل -- فقط استدعاء مباشر يتحقق: هل التحقق الأمني
المزعوم غيابه (أو وجوده) صحيح فعليًا وقت التنفيذ.
"""
from dataclasses import dataclass
from pathlib import Path
import json

@dataclass
class TestAppSpec:
    candidate_id: str
    target_class: str          # مثال: com.android.server.pm.PackageManagerService
    target_method: str
    method_params: list[tuple[str, str]]   # [(type, sample_value), ...]
    caller_uid_simulation: str  # 'untrusted_third_party' | 'system_app' | 'shell'

MANIFEST_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.afvrm.labtest.{candidate_id}">
    <uses-permission android:name="android.permission.INTERACT_ACROSS_USERS" />
    <application android:label="AFVRM Lab Test">
        <activity android:name=".TestActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""

ACTIVITY_TEMPLATE = """
package com.afvrm.labtest.{candidate_id};

import android.app.Activity;
import android.os.Bundle;
import android.util.Log;

public class TestActivity extends Activity {{
    private static final String TAG = "AFVRM_LAB";

    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
        Log.i(TAG, "LAB_TEST_START candidate={candidate_id}");
        try {{
            {invocation_code}
            Log.i(TAG, "LAB_TEST_RESULT status=completed_without_exception");
        }} catch (SecurityException e) {{
            Log.i(TAG, "LAB_TEST_RESULT status=security_exception message=" + e.getMessage());
        }} catch (Exception e) {{
            Log.i(TAG, "LAB_TEST_RESULT status=other_exception message=" + e.getMessage());
        }}
        Log.i(TAG, "LAB_TEST_END candidate={candidate_id}");
        finish();
    }}
}}
"""

def build_invocation_code(spec: TestAppSpec) -> str:
    """يبني استدعاء الـmethod عبر reflection -- لأن معظم system services
    غير قابلة للربط المباشر من تطبيق طرف ثالث عاديًا؛ الـreflection هنا
    يحاكي بالضبط ما يستطيع أي تطبيق فعله عبر Binder interface العام."""
    params_str = ", ".join(f'"{v}"' for _, v in spec.method_params)
    param_types_str = ", ".join(f"{t}.class" for t, _ in spec.method_params)

    return f"""
        Class<?> serviceClass = Class.forName("{spec.target_class}");
        Object serviceInstance = getSystemService(
            serviceClass.getSimpleName().toLowerCase()
        );
        java.lang.reflect.Method targetMethod = serviceClass.getMethod(
            "{spec.target_method}", {param_types_str}
        );
        targetMethod.invoke(serviceInstance, {params_str});
    """.strip()

def generate_test_project(spec: TestAppSpec, output_dir: Path) -> Path:
    project_dir = output_dir / f"labtest_{spec.candidate_id}"
    src_dir = project_dir / "src" / "main" / "java" / "com" / "afvrm" / "labtest" / spec.candidate_id
    src_dir.mkdir(parents=True, exist_ok=True)

    manifest = MANIFEST_TEMPLATE.format(candidate_id=spec.candidate_id)
    (project_dir / "AndroidManifest.xml").write_text(manifest)

    invocation_code = build_invocation_code(spec)
    activity_code = ACTIVITY_TEMPLATE.format(
        candidate_id=spec.candidate_id, invocation_code=invocation_code
    )
    (src_dir / "TestActivity.java").write_text(activity_code)

    metadata = {
        "candidate_id": spec.candidate_id,
        "target": f"{spec.target_class}.{spec.target_method}",
        "caller_simulation": spec.caller_uid_simulation,
    }
    (project_dir / "lab_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False)
    )

    return project_dir
```

> **قيد صريح:** هذا المولّد يدعم فقط استدعاءات عبر `getSystemService` + reflection قياسي -- وهو بالضبط نفس المسار المتاح لأي تطبيق طرف ثالث عادي على الجهاز. **لا يُستخدَم أي صلاحيات root أو تجاوز أمني** لتنفيذ الاستدعاء نفسه؛ الهدف هو محاكاة زاوية هجوم واقعية (تطبيق عادي يحاول الاستدعاء)، وليس تجاوز الحماية للوصول لاستدعاء غير متاح أصلًا لتطبيق عادي.

### 66.2 محاكاة هوية المتصل

```python
# lab/caller_identity_simulator.py
"""
Android لا يسمح لتطبيق عادي بانتحال UID تطبيق آخر مباشرة --
لذلك نحاكي "الهوية المُفتَرَضة" عبر تثبيت التطبيق كمستخدم Android
مختلف (multi-user profile)، وهو أقرب تمثيل واقعي متاح دون كسر
حدود النظام نفسها.
"""
import subprocess

CALLER_PROFILES = {
    "untrusted_third_party": {"user_id": 10, "install_flags": []},
    "system_app": {"user_id": 0, "install_flags": ["-g"]},
    "shell": {"user_id": 0, "install_flags": ["--user", "0"]},
}

def ensure_test_user_exists(adb_serial: str, user_id: int):
    subprocess.run(
        ["adb", "-s", adb_serial, "shell", "pm", "create-user",
         f"lab_user_{user_id}"],
        capture_output=True, text=True
    )

def install_as_caller(adb_serial: str, apk_path: str, caller_type: str):
    profile = CALLER_PROFILES[caller_type]
    ensure_test_user_exists(adb_serial, profile["user_id"])

    cmd = ["adb", "-s", adb_serial, "install"] + profile["install_flags"] + [apk_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stdout + result.stderr
```

---

## الفصل 67: التشغيل، المراقبة، وتفسير النتائج

### 67.1 استعادة حالة نظيفة قبل كل اختبار

```python
# lab/avd_controller.py
import subprocess
import time

def start_avd_from_snapshot(avd_name: str, snapshot_name: str = "clean_baseline"):
    """كل اختبار يبدأ من نفس النقطة تمامًا -- يمنع تأثير أي اختبار
    سابق على نتائج الاختبار الحالي."""
    subprocess.Popen([
        "emulator", "-avd", avd_name,
        "-snapshot", snapshot_name,
        "-no-snapshot-save",
        "-no-audio", "-no-window",
    ])
    time.sleep(30)  # هامش إقلاع -- يُضبَط تجريبيًا حسب سرعة الجهاز

def create_clean_snapshot(adb_serial: str, snapshot_name: str = "clean_baseline"):
    """يُشغَّل مرة واحدة فقط بعد أول إقلاع ناجح للـAVD."""
    subprocess.run(
        ["adb", "-s", adb_serial, "emu", "avd", "snapshot", "save", snapshot_name],
        capture_output=True, text=True
    )

def stop_avd(adb_serial: str):
    subprocess.run(["adb", "-s", adb_serial, "emu", "kill"], capture_output=True)
```

### 67.2 مراقبة التنفيذ عبر Frida

```python
# lab/frida_monitor.py
"""
يحقن hook في system_server (أو التطبيق المُختبَر) لمراقبة استدعاء
الـmethod المستهدفة مباشرة -- دليل تنفيذي فعلي، وليس استنتاجًا
من الكود الثابت فقط.
"""
import frida

FRIDA_SCRIPT_TEMPLATE = """
Java.perform(function () {{
    var TargetClass = Java.use("{target_class}");
    TargetClass.{target_method}.implementation = function () {{
        send({{
            event: "method_entered",
            method: "{target_method}",
            args: JSON.stringify(arguments)
        }});
        try {{
            var result = this.{target_method}.apply(this, arguments);
            send({{event: "method_returned", status: "success"}});
            return result;
        }} catch (e) {{
            send({{
                event: "method_threw",
                exception_class: e.getClass ? e.getClass().getName() : "unknown",
                message: e.toString()
            }});
            throw e;
        }}
    }};
}});
"""

def monitor_test_run(adb_serial: str, target_class: str, target_method: str,
                      package_name: str, timeout_seconds: int = 15) -> list[dict]:
    device = frida.get_device(adb_serial)
    events = []

    def on_message(message, data):
        if message["type"] == "send":
            events.append(message["payload"])

    session = device.attach(package_name)
    script_code = FRIDA_SCRIPT_TEMPLATE.format(
        target_class=target_class, target_method=target_method
    )
    script = session.create_script(script_code)
    script.on("message", on_message)
    script.load()

    import time
    time.sleep(timeout_seconds)

    session.detach()
    return events
```

### 67.3 تفسير النتائج

```python
# lab/result_interpreter.py
"""
يحوّل الأحداث الخام من Frida + logcat إلى حكم نهائي يُضاف لـGround
Truth (الفصل 39) -- بنفس صرامة قواعد القرار الحتمية المستخدمة في
باقي أجزاء الكتاب، وليس تفسيرًا حرًا.
"""
from dataclasses import dataclass
from enum import Enum

class LabVerdict(str, Enum):
    CONFIRMED_VULNERABLE = "confirmed_vulnerable"
    CONFIRMED_SECURE = "confirmed_secure"
    INCONCLUSIVE = "inconclusive"

@dataclass
class LabResult:
    candidate_id: str
    verdict: LabVerdict
    evidence: list[str]
    raw_events: list[dict]

def interpret_run(candidate_id: str, frida_events: list[dict],
                   logcat_lines: list[str]) -> LabResult:
    threw_security_exception = any(
        e.get("event") == "method_threw" and
        "SecurityException" in e.get("exception_class", "")
        for e in frida_events
    )
    method_entered = any(e.get("event") == "method_entered" for e in frida_events)
    method_returned_success = any(
        e.get("event") == "method_returned" and e.get("status") == "success"
        for e in frida_events
    )

    lab_start_seen = any("LAB_TEST_START" in line for line in logcat_lines)
    lab_end_seen = any("LAB_TEST_END" in line for line in logcat_lines)

    if not (lab_start_seen and lab_end_seen):
        return LabResult(
            candidate_id=candidate_id, verdict=LabVerdict.INCONCLUSIVE,
            evidence=["Test app did not complete its run -- installation, "
                      "launch, or instrumentation likely failed"],
            raw_events=frida_events,
        )

    if not method_entered:
        return LabResult(
            candidate_id=candidate_id, verdict=LabVerdict.INCONCLUSIVE,
            evidence=["Target method was never entered -- reflection call "
                      "may have failed before reaching the target"],
            raw_events=frida_events,
        )

    if threw_security_exception:
        return LabResult(
            candidate_id=candidate_id, verdict=LabVerdict.CONFIRMED_SECURE,
            evidence=["Method threw SecurityException -- authorization "
                      "check rejected the simulated caller as expected"],
            raw_events=frida_events,
        )

    if method_returned_success:
        return LabResult(
            candidate_id=candidate_id, verdict=LabVerdict.CONFIRMED_VULNERABLE,
            evidence=["Method completed successfully without any security "
                      "rejection -- the privileged operation was reachable "
                      "by the simulated untrusted caller"],
            raw_events=frida_events,
        )

    return LabResult(
        candidate_id=candidate_id, verdict=LabVerdict.INCONCLUSIVE,
        evidence=["Method was entered but outcome could not be determined "
                  "from available events"],
        raw_events=frida_events,
    )
```

### 67.4 دمج نتيجة المختبر في Ground Truth

```python
# lab/promote_to_ground_truth.py
from lab.result_interpreter import LabVerdict

def promote_lab_result(finding: dict, lab_result) -> dict:
    """يرفع finding من verdict نموذج (ثقة احتمالية) إلى ground truth
    مؤكَّد بدليل تنفيذي فعلي -- أعلى مستوى ثقة ممكن في هرمية الفصل 39.2."""
    updated = dict(finding)

    if lab_result.verdict == LabVerdict.CONFIRMED_VULNERABLE:
        updated["ground_truth_status"] = "confirmed_security_issue"
        updated["confidence"] = 0.98
    elif lab_result.verdict == LabVerdict.CONFIRMED_SECURE:
        updated["ground_truth_status"] = "false_positive"
        updated["confidence"] = 0.98
    else:
        updated["ground_truth_status"] = "unconfirmed"

    updated["lab_evidence"] = lab_result.evidence
    return updated
```

### 67.5 نطاق الاستخدام — تذكير أخير وحاسم

هذا المختبر بالكامل مصمَّم للعمل **حصريًا** على:
- كود AOSP المُجمَّع محليًا (الجزء السادس)
- Emulator يعمل على جهازك أنت
- تطبيقات اختبار مولَّدة آليًا لا تتصل بأي خدمة خارجية

**لا يوجد أي مسار في هذا التصميم يتصل بالإنترنت، ولا يستهدف أي نظام إنتاجي حقيقي، ولا يحاول تجاوز عزل الـEmulator نفسه.** أي توسيع لهذا المختبر ليشمل أهدافًا خارج AOSP المحلي (تطبيقات مثبَّتة من مصادر خارجية، أنظمة شبكية، مواقع حقيقية) يخرج تمامًا عن نطاق هذا المشروع ولن يُدعَم.

> **Definition of Done -- الجزء الثالث والثلاثون:** تشغيل ناجح لدورة كاملة (build test app إلى install إلى launch إلى Frida monitor إلى interpret) على 3 Candidates حقيقية على الأقل من الأجزاء السابقة، مع الحصول على `LabVerdict` واضح لكل واحدة (وليس `INCONCLUSIVE` للكل -- لو حصل ده، المشكلة على الأرجح في إعداد الـreflection call أو صلاحيات الـAVD نفسها)، ومراجعة يدوية تؤكد أن كل `CONFIRMED_VULNERABLE` يطابق فعليًا حكم النموذج/الـAgent الأصلي أو يوضّح التناقض إن وُجد.

---

[← الجزء الثاني والثلاثون](./part-32-agent-architecture.md) · [الفهرس](./README.md) · [الجزء الرابع والثلاثون →](./part-34-confirmation-tiers-containment.md)
