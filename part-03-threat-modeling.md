[← الجزء الثاني](./part-02-android-fundamentals.md) · [الفهرس](./README.md)

# الجزء الثالث: Threat Modeling للكود

## الفصل 7: Trust Boundaries

كل Finding منتج من النظام **يجب** أن يحدد Trust Boundary صريح — الحد الذي عبرته بيانات مسيطَر عليها من طرف غير موثوق إلى عملية ذات صلاحية. بدون هذا التحديد، الـFinding مجرد ملاحظة عامة غير قابلة للتحقق.

### 7.1 نموذج الحدود الأساسي

```
Untrusted App
     |
     | Binder
     ↓
system_server
     |
     ↓
Privileged Resource
```

هذا هو أبسط شكل، لكن في الواقع الحدود متعددة الطبقات:

```
Untrusted App (UID A, userId 0)
     | Binder
     ↓
system_server (يفقد هوية A بعد clearCallingIdentity)
     | internal call
     ↓
Helper Service (قد يخدم أكثر من مستدعٍ داخلي)
     | file / IPC / HAL
     ↓
Privileged Resource (بيانات مستخدم آخر، ملف نظام، إلخ)
```

كل سهم في هذا المخطط هو Trust Boundary محتمل مستقل، ويجب تقييمه بمفرده.

### 7.2 تصنيف القيم عبر الحدود

النموذج يجب أن يصنّف كل قيمة (parameter, field, return value) ضمن إحدى الحالات التالية، ولا يفترض أبدًا الحالة الأكثر أمانًا دون دليل:

| الحالة | التعريف | مثال |
|---|---|---|
| **Trusted** | مصدرها داخل حدود system_server نفسه، غير قابلة للتأثير من المتصل | ثابت داخلي، أو قيمة محسوبة من `Binder.getCallingUid()` نفسه |
| **Untrusted** | تأتي مباشرة كمعامل من المتصل بدون أي معالجة | `String packageName` في توقيع method عام |
| **Derived** | نتيجة عملية حسابية على قيمة untrusted | `UserHandle.getUserId(callingUid)` — مشتقة لكن من مصدر موثوق (UID الفعلي) |
| **Validated** | untrusted سابقًا، لكن مرّت بتحقق كافٍ وموثّق ضد الهوية الفعلية | `packageName` بعد استدعاء `verifyPackageBelongsToUid()` |
| **Partially validated** | مرّت بتحقق جزئي لا يغطي كل استخدام لاحق لها | تحقق من وجود الـpermission فقط دون تحقق من `userId` المستهدف |
| **Unknown** | لا يمكن تحديد حالتها من السياق المُعطى (تحتاج retrieval إضافي) | قيمة قادمة من helper method غير مرئي التعريف |

### 7.3 القاعدة الافتراضية

> **افتراض أساسي:** أي قيمة قادمة كمعامل من Binder interface تُصنَّف تلقائيًا كـ **Untrusted** حتى تثبت العكس عبر Evidence مباشر من الكود المُعطى. لا يجوز للنموذج ترقية الحالة إلى Validated بناءً على اسم method يبدو أنه يتحقق (مثل الاعتماد على اسم `checkCaller` وحده دون رؤية تعريفه).

مثال على الخطأ الشائع:

```java
void updateSomething(int targetUserId, String packageName) {
    // النموذج يجب ألا يفترض أن targetUserId أو packageName موثوقان
    // فقط لأن أسماءهما "تبدو رسمية"
}
```

### 7.4 Schema قابل للاستخدام من النموذج

```json
{
  "trust_boundary": {
    "boundary_id": "app_to_system_server",
    "source_side": {
      "identity": "calling_app_uid",
      "trust_level": "untrusted"
    },
    "destination_side": {
      "identity": "system_server",
      "trust_level": "trusted"
    },
    "crossing_values": [
      {
        "name": "targetUserId",
        "classification": "untrusted",
        "validated_by": null,
        "validated_before_identity_loss": false
      },
      {
        "name": "packageName",
        "classification": "partially_validated",
        "validated_by": "checkCallingPermission(MANAGE_USERS)",
        "validated_before_identity_loss": true,
        "note": "permission check only — no explicit UID-to-package ownership verification"
      }
    ]
  }
}
```

هذا الـSchema هو ما سيُستخدم لاحقًا كجزء من `analysis.trust_boundary` في الـDataset (الفصل 27).

---

## الفصل 8: Source → Sink Analysis

هذا الفصل يبني على مفهوم شائع في تحليل الأمان الثابت (Taint Analysis) لكن مُكيَّف لسياق Android Framework تحديدًا، وليس تطبيقًا حرفيًا لأدوات taint تقليدية.

### 8.1 تعريف Source

**Source** هو أي مدخل يستطيع المهاجم (تطبيق غير موثوق) التحكم في قيمته كليًا أو جزئيًا:

- Binder method parameters (الأكثر شيوعًا)
- Intent extras (`getStringExtra`, `getIntExtra`, ...)
- URIs ممرَّرة عبر ContentProvider أو Intent
- بيانات Parcel مخصصة (custom `readFromParcel`)
- Callbacks مسجَّلة من تطبيق طرف ثالث (الكود اللي جوه الـcallback نفسه غير موثوق)
- `packageName` قادم من المتصل
- `userId` / `UserHandle` قادم من المتصل
- مسارات ملفات (paths) مبنية جزئيًا من مدخلات المتصل
- File descriptors ممرَّرة عبر Binder

### 8.2 تعريف Sink

**Sink** هو عملية ذات قيمة أمنية — الوصول إليها بدون تحقق كافٍ هو جوهر الثغرة:

- الوصول لبيانات مستخدم (Android user) آخر غير مالك العملية
- تعديل إعداد نظام عام (system setting)
- فتح أو كتابة ملف بصلاحيات مرتفعة
- إرسال Intent كـsystem (باسم `system_server`)
- تنفيذ عملية تحمل هوية مرتفعة بعد identity transition
- منح صلاحية (grant permission) لتطبيق آخر
- الوصول إلى خدمة privileged أو مكوّن حساس

### 8.3 التسلسل الذي يتتبعه النموذج

```
Source
 ↓
Transformations   (parsing, casting, string building)
 ↓
Validation        (permission check? cross-user check? ownership check?)
 ↓
Identity change    (clearCallingIdentity وما شابه)
 ↓
Sink
```

النقطة الحرجة هي **ترتيب** الخطوات، وليس مجرد وجودها. Validation يجب أن يحدث **قبل** فقدان الهوية الأصلية و**قبل** الوصول إلى الـSink، وإلا فالتحقق عديم القيمة الأمنية بصرف النظر عن وجوده في مكان آخر بالملف.

### 8.4 مثال Source → Sink كامل

```java
public void grantAccess(String packageName, int targetUserId, Uri uri) {
    // Source #1: packageName (untrusted)
    // Source #2: targetUserId (untrusted)
    // Source #3: uri (untrusted)

    int callingUid = Binder.getCallingUid();

    // Validation: يتحقق فقط من ownership الـpackage — لا يتحقق من targetUserId
    enforcePackageOwnership(callingUid, packageName);

    long token = Binder.clearCallingIdentity();   // Identity change
    try {
        // Sink: منح صلاحية وصول لموارد مستخدم آخر بدون تحقق cross-user
        mUriGrantsManager.grantUriPermission(packageName, uri, targetUserId);
    } finally {
        Binder.restoreCallingIdentity(token);
    }
}
```

هنا الـTaint path واضح: `targetUserId` وصل إلى Sink حساس (`grantUriPermission`) دون أن يمر بأي Validation خاص به — رغم أن `packageName` نفسه مررّ بتحقق. هذا مثال نموذجي على validation جزئي يغطي متغيرًا واحدًا فقط بينما الثغرة في متغير آخر بجانبه.

---

## الفصل 9: Security Invariants — المكتبة الأساسية

هذه المكتبة هي العمود الفقري لكل مراحل المشروع اللاحقة: توليد الـDataset، تصميم الـTaxonomy، وبناء الـStatic Facts Extractor. كل Invariant هو قاعدة عامة، مستقلة عن أي CVE بعينه، يبحث النموذج عن انتهاكها.

### 9.1 UID

1. A caller-controlled value must never be treated as an authoritative UID without cross-referencing `Binder.getCallingUid()`.
2. Comparing UIDs for authorization must account for both `appId` and `userId` components, not raw numeric equality alone.
3. A UID obtained after `clearCallingIdentity()` must not be used as if it were the original caller's UID.
4. Isolated UIDs must not be granted access equivalent to a full application UID.
5. Shared UID membership must not be assumed without an explicit signature/package check.

### 9.2 Package Identity

6. A caller-supplied `packageName` must not be trusted without verifying it belongs to the calling UID.
7. Package ownership verification performed for one operation must not be reused implicitly to authorize a different, unrelated operation.
8. A package's privileged status (system, privileged, pre-installed) must be verified via PackageManager, not inferred from its name or path string.
9. Uninstalled or disabled packages must not be treated as valid authorization subjects.

### 9.3 Binder

10. `Binder.clearCallingIdentity()` must always be paired with `restoreCallingIdentity()` in a `finally` block.
11. Any authorization decision must be made using the caller's identity captured before `clearCallingIdentity()`, not after.
12. A nested Binder call made after `clearCallingIdentity()` must not be treated by the downstream service as if it originated from the original external caller.
13. `getCallingPid()` must not be used as a substitute for UID-based authorization, since PIDs are reusable.
14. Oneway Binder calls must not assume the caller identity remains available for asynchronous follow-up logic.

### 9.4 Permissions

15. A `checkCallingPermission` returning granted does not, by itself, authorize an operation on a different Android user.
16. `enforceCallingOrSelfPermission` must not be substituted for `enforceCallingPermission` unless self-invocation is an intended, reviewed case.
17. A signature-level permission check must verify the actual signing certificate relationship, not merely the permission's declared protection level.
18. Revoked or not-yet-granted runtime permissions must be re-checked at the point of the privileged operation, not only at registration time.
19. A permission check performed in a caller (e.g., an Activity) must not be assumed to have already occurred when the flow reaches system_server.

### 9.5 Cross-user

20. An operation targeting a `userId` different from the caller's own must require an explicit cross-user authorization check (e.g., `INTERACT_ACROSS_USERS`).
21. A cross-user check must occur before the identity used to validate it is lost or replaced.
22. Work profile boundaries must be treated as a cross-user boundary equivalent to distinct human users unless explicitly documented otherwise.
23. A default fallback of `UserHandle.CURRENT` or `UserHandle.ALL` in a caller-controlled context must be treated as a potential cross-user exposure.
24. Cross-user authorization granted for read access must not be assumed sufficient for write or delete operations.

### 9.6 AppOps

25. A granted permission does not imply the corresponding AppOps mode allows the operation at runtime.
26. AppOps checks must be evaluated using the actual calling package and UID pair, not a cached or default value.
27. `AppOpsManager.noteOp` results must gate the sensitive operation itself, not merely be logged after the fact.
28. An AppOps mode of `MODE_IGNORED` must result in a silent no-op or explicit denial, not a partial execution of the privileged path.

### 9.7 Intents

29. Extras read from an incoming `Intent` must be treated as fully attacker-controlled, including type and presence.
30. An implicit `Intent` sent with system-level identity must not include caller-controlled component targeting that could be hijacked.
31. Broadcast receivers processing system-relevant actions must verify the sender's identity when the action implies a trust assumption.
32. `Intent` extras used to reconstruct a `UserHandle` or target UID must be validated identically to a direct method parameter.

### 9.8 PendingIntent

33. A `PendingIntent` created with caller-supplied component or package data must not be trusted to represent the original creator's authority implicitly.
34. Mutable `PendingIntent` objects passed to less-trusted components must not allow their underlying `Intent` to be modified into a privileged action.
35. A `PendingIntent` sent on behalf of the system must not be constructable by an untrusted caller with attacker-chosen extras that survive into the privileged execution.

### 9.9 URI

36. A `Uri` received from an untrusted caller must not be resolved or opened without permission-granted verification for that specific URI.
37. `content://` URIs must not be trusted to resolve to the caller's own data without an explicit authority/ownership check.
38. URI permission grants must not be extended implicitly beyond their declared scope (read vs. write, single item vs. tree).

### 9.10 Files

39. File paths built by concatenating caller-controlled strings must be canonicalized and validated against a permitted root before use.
40. A file operation performed after `clearCallingIdentity()` must not resolve a path that was only validated against the original caller's sandbox.
41. Symbolic links must not be trusted to resolve within the expected directory boundary without canonical path verification.

### 9.11 State

42. A security decision must be re-validated at the point of the privileged action if any state (permission, user, ownership) could have changed since the decision was first made.
43. Time-of-check-to-time-of-use (TOCTOU) gaps between validation and privileged use must not exist across asynchronous boundaries (async tasks, handlers, callbacks).
44. Cached authorization results must include an explicit invalidation path tied to the underlying permission/AppOps/ownership state.

### 9.12 Race Conditions

45. Concurrent modification of shared privileged state (e.g., user records, package state) must be protected by synchronization equivalent to the sensitivity of the state.
46. A check-then-act sequence on shared mutable state must be atomic with respect to other threads capable of altering that state between check and act.

### 9.13 Privilege Transitions

47. A transition from application-level UID to `system_server` identity must not silently persist beyond the intended scope of the privileged operation.
48. A shell-initiated operation (`adb shell`) must not be granted the same implicit trust as a genuine system component invocation.
49. An operation reachable from both a privileged system app and a normal third-party app must apply identical authorization regardless of the calling app's own privilege level, unless that differentiation is itself explicitly and correctly checked.
50. Escalation from a lower-privileged isolated process to a full app-level or system-level operation must require an explicit, auditable authorization step.

> **ملاحظة تصميمية:** هذه القائمة هي إصدار v0.1 من المكتبة (50 Invariant). في الفصل 22 (Candidate Generator) وحدة الـStatic Analyzer ستربط كل Candidate بواحد أو أكثر من أرقام هذه القائمة كـ`missing_invariant` أو `satisfied_invariant`، وهذا الربط هو ما يسمح لاحقًا بقياس **Security Invariant Accuracy** (الفصل 2) بشكل آلي بدل الاعتماد على مطابقة نصية.

---

[← الجزء الثاني](./part-02-android-fundamentals.md) · [الفهرس](./README.md) · [الجزء الرابع →](./part-04-vulnerability-taxonomy.md)
