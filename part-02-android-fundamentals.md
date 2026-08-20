[← الجزء الأول](./part-01-project-definition.md) · [الفهرس](./README.md)

# الجزء الثاني: Android Security Fundamentals

## الفصل 3: Android Security Architecture

هذا الفصل هو الأساس الذي سيُبنى عليه كل تحليل لاحق. كل مفهوم هنا مرتبط مباشرة بحقل أو قرار سيتخذه النموذج لاحقًا — لسنا هنا في شرح أكاديمي عام.

### 3.1 الـSandbox ونموذج UID

كل تطبيق Android يعمل داخل Linux process له UID خاص به (عادةً في المدى 10000+ لتطبيقات الطرف الثالث). الـSandbox الأساسي في Android مبني فوق فصل عمليات Linux التقليدي، وليس شيئًا إضافيًا فوقه.

| المفهوم | المعنى العملي | الحقل في Security Facts |
|---|---|---|
| UID | هوية Linux الفعلية للعملية المتصلة | `caller_identity.uid` |
| PID | معرف العملية — غير موثوق للقرارات الأمنية طويلة الأمد (قابل لإعادة الاستخدام) | `caller_identity.pid` (سياقي فقط) |
| appId | الجزء الثابت من UID المرتبط بالتطبيق نفسه بصرف النظر عن المستخدم | `package_identity.app_id` |
| userId | رقم ملف Android (multi-user profile) الذي يعمل فيه appId | `cross_user_checks.target_user` |
| UserHandle | تمثيل مركّب لـ(userId) يُستخدم في الـAPIs بدل رقم خام | `identity_transitions` |
| shared UID | أكثر من تطبيق (بنفس التوقيع) يشتركون في UID واحد — قديم ويُهمل تدريجيًا لكنه لا يزال موجودًا في كود قديم | `legacy_pattern` flag |
| isolated UID | UID مؤقت شديد التقييد لعمليات معزولة (مثل WebView المعزول) | `trust_level = minimal` |
| system / root / shell UID | هويات مميزة ذات صلاحيات مرتفعة داخل النظام نفسه | `trust_level = system/privileged` |

### 3.2 Multi-user وProfiles

Android يدعم أكثر من مستخدم (أو Profile مثل Work Profile) على نفس الجهاز. كل مستخدم له نسخته من كل تطبيق مثبت، ولكل نسخة UID مختلف يُحسب تقريبًا كـ:

```
UID = userId * 100000 + appId
```

هذه المعادلة هي السبب الجوهري لوجود فئة كاملة من الثغرات تسمى **Cross-user vulnerabilities**: عملية تسمح لتطبيق في Profile واحد بالتأثير على بيانات أو عمليات مستخدم آخر بسبب عدم التحقق من تطابق `userId` المُستهدف مع صلاحية المتصل.

### 3.3 SELinux وPermissions

| الطبقة | دورها | لماذا النموذج يحتاجها |
|---|---|---|
| SELinux | طبقة MAC على مستوى kernel تفرض قيودًا حتى لو سمح Linux DAC بالعملية | حد أقصى إضافي — لكن Framework bugs غالبًا داخل ما تسمح به السياسة أصلًا |
| Normal permissions | تُمنح تلقائيًا عند التثبيت | خطر منخفض عادةً كـsource وحدها |
| Signature permissions | فقط لتطبيقات موقّعة بنفس مفتاح النظام | تُستخدم كحد أمني قوي — أي bypass لها خطير جدًا |
| Privileged / system permissions | لتطبيقات مثبتة في partitions مميزة فقط | نقطة تركيز رئيسية — bypass هنا يعني تصعيد صلاحيات حقيقي |
| AppOps | طبقة تحكم تشغيلية إضافية فوق الـPermissions (يمكن أن تُلغى وقت التشغيل رغم منح الصلاحية) | غالبًا مصدر أخطاء لأن المطورين ينسون التحقق منها رغم وجود permission check |
| Exported components | مكوّنات (Activity/Service/Receiver/Provider) يمكن الوصول إليها من تطبيقات أخرى | أول نقطة دخول يجب فحصها لأي هجوم IPC |
| Binder IPC | آلية الاتصال بين العمليات في Android بالكامل | قلب كل تحليل في هذا المشروع (الفصل 5) |
| system_server | عملية واحدة ضخمة تستضيف معظم الخدمات المميزة (PackageManager, ActivityManager, ...) | الهدف الرئيسي شبه الحصري لهذا المشروع |

> **لماذا هذا يهم النموذج تحديدًا:** أكبر خطأ منهجي هو اعتبار "وجود permission check" دليلًا كافيًا على الأمان. الجدول أعلاه يوضح أن هناك طبقتين مستقلتين على الأقل (Permission وAppOps) — تجاوز التحقق من واحدة فقط لا يعني بالضرورة عدم وجود ثغرة.

---

## الفصل 4: AOSP Architecture for Security Research

المشروع لن يبحث في AOSP كاملة عشوائيًا. سنركز جهدنا بدقة على المسارات الأعلى كثافة في الثغرات التاريخية، مع معرفة متى نحتاج للخروج من `frameworks/base`.

### 4.1 المسارات ذات الأولوية

```
frameworks/base/
├── services/core/java/com/android/server/   ← الأولوية القصوى
│                                              (معظم system services)
├── core/java/android/                        ← تعريفات الـAPI العامة
├── services/                                  ← خدمات متخصصة أخرى
├── packages/                                  ← تطبيقات نظام (SystemUI, Settings)
├── telecomm/                                  ← خدمات الاتصال
├── location/                                  ← خدمات الموقع
└── media/                                     ← خدمات الوسائط
```

### 4.2 متى نخرج خارج frameworks/base

| المصدر | متى نحتاجه |
|---|---|
| native services (system/*) | عندما تكون العملية المميزة تُنفَّذ فعليًا في native daemon (مثل installd) وليس في Java framework فقط |
| system/core | لفهم آليات أساسية مثل init، أو حدود صلاحيات على مستوى النظام الأدنى |
| packages/modules | لخدمات Mainline الحديثة المفصولة عن AOSP الأساسي (مثل بعض وحدات الشبكة أو الوسائط) |
| hardware interfaces (HAL) | عندما تعبر البيانات من Framework إلى hardware-backed service وقد يكون التحقق موزّعًا بين الطبقتين |
| SELinux policies | للتأكد ما إذا كانت العملية المميزة مسموحة أصلًا على مستوى الـMAC، كسياق إضافي وليس بديلاً عن تحليل الكود |

### 4.3 من AIDL إلى Service Implementation

معظم واجهات Binder مُعرّفة كملفات `.aidl`، والتي تُترجم إلى Stub classes. تتبع الاستدعاء يمر بالمسار التالي:

```
Client app
   ↓ (calls interface method)
IFooService.aidl → IFooService.Stub (generated)
   ↓ (onTransact)
FooManagerService extends IFooService.Stub
   ↓ (actual method body)
الكود الفعلي الذي نحلله
```

النموذج يجب أن يعرف أن الأمثلة اللي هيشوفها غالبًا هي implementation داخل class يمتد Stub، وأن `onTransact` نفسه نادرًا ما يحتاج تعديل — التركيز يكون على أجسام الـmethods المُطبَّقة.

---

## الفصل 5: Binder Security Model

هذا أهم فصل تقني في الجزء الثاني، لأن نسبة كبيرة من الثغرات المستهدفة تدور حول identity transitions عبر Binder.

### 5.1 الـAPIs الأساسية

```java
int callingUid = Binder.getCallingUid();
int callingPid = Binder.getCallingPid();

long token = Binder.clearCallingIdentity();
try {
    // الكود هنا يعمل بهوية system_server، ليس هوية المتصل
    doPrivilegedWork();
} finally {
    Binder.restoreCallingIdentity(token);
}
```

### 5.2 دورة حياة الهوية (Identity Lifetime)

- أثناء معالجة Binder transaction، `getCallingUid()`/`getCallingPid()` يرجعان هوية المُستدعي الفعلي طالما لم تُستدعَ `clearCallingIdentity()`.
- بعد `clearCallingIdentity()`، أي استدعاء لاحق لـ`getCallingUid()` داخل نفس thread سيرجع UID الخاص بـsystem_server نفسه — وليس المتصل الأصلي.
- **Nested calls:** لو داخل كتلة `clearCallingIdentity()` تم استدعاء Binder آخر إلى خدمة ثانية، تلك الخدمة سترى system_server كمتصل، وليس التطبيق الأصلي — وهذا بالضبط سبب وجود الآلية أصلًا (لتمكين system_server من تنفيذ عمليات مميزة نيابة عن التطبيق بعد التحقق).
- `restoreCallingIdentity()` إلزامية داخل `finally` لضمان عدم تسرب الهوية الخاطئة لبقية معالجة الـtransaction.

### 5.3 لماذا توجد الآلية أصلًا

`clearCallingIdentity()` ليست خطأً تصميميًا، بل هي الآلية القياسية التي تمكّن system_server من تنفيذ عمليات تحتاج صلاحيات النظام (مثل كتابة ملف نظام، أو تعديل إعداد عام) نيابة عن تطبيق طلب عملية مشروعة. **المشكلة الأمنية لا تنشأ من وجودها، بل من ترتيب العمليات حولها.**

### 5.4 النمط الخطر مقابل النمط الآمن

**مثال Vulnerable:**

```java
public void updateUserSetting(int targetUserId, String key, String value) {
    // لا يوجد أي تحقق من صلاحية caller تجاه targetUserId
    long token = Binder.clearCallingIdentity();
    try {
        settingsProvider.write(targetUserId, key, value);
    } finally {
        Binder.restoreCallingIdentity(token);
    }
}
```

**المشكلة:** `targetUserId` قادم كاملاً من المتصل (caller-controlled)، ولا يوجد أي `enforceCrossUserPermission` قبل الوصول للعملية المميزة. بعد `clearCallingIdentity()`، أي تحقق لاحق داخل `settingsProvider.write()` لن يرى الهوية الأصلية للمتصل — الفرصة الوحيدة للتحقق كانت قبل هذا السطر ولم تحدث.

**مثال Secure (يبدو مشابهًا لكنه آمن):**

```java
public void updateUserSetting(int targetUserId, String key, String value) {
    int callingUid = Binder.getCallingUid();
    // التحقق يحدث قبل فقدان الهوية الأصلية
    mUserManagerInternal.enforceCrossUserPermission(
        callingUid, targetUserId, "updateUserSetting");

    long token = Binder.clearCallingIdentity();
    try {
        settingsProvider.write(targetUserId, key, value);
    } finally {
        Binder.restoreCallingIdentity(token);
    }
}
```

الفرق الوحيد هو سطر واحد قبل `clearCallingIdentity()`، لكنه يقلب الحكم بالكامل. هذا بالضبط نوع الـHard Negative الذي سنبنيه بكثافة في الفصل 31 — لأن التمييز بين المثالين هو جوهر قدرة النموذج على تقليل False Positives.

**مثال Ambiguous (يحتاج مزيد من السياق):**

```java
public void updateUserSetting(int targetUserId, String key, String value) {
    int callingUid = Binder.getCallingUid();
    checkCaller(callingUid, targetUserId);   // ← تعريف checkCaller غير معروف هنا

    long token = Binder.clearCallingIdentity();
    try {
        settingsProvider.write(targetUserId, key, value);
    } finally {
        Binder.restoreCallingIdentity(token);
    }
}
```

الحكم الصحيح هنا هو `insufficient_context`: لا يمكن معرفة ما إذا كانت `checkCaller()` تُجري تحققًا كافيًا للـcross-user authorization بدون رؤية تعريفها. هذا هو النمط الذي سيتكرر آلاف المرات في الـDataset (الفصل 32).

---

## الفصل 6: Android Authorization

الـAuthorization في Android متعدد الطبقات، وأي طبقة واحدة وحدها غالبًا غير كافية للحكم بالأمان.

### 6.1 أنواع فحوصات الصلاحيات

| الفحص | ماذا يتحقق منه | الخطأ الشائع |
|---|---|---|
| checkCallingPermission / enforceCallingPermission | أن المتصل يملك permission معيّنة مُعلنة في manifest | لا يتحقق من هوية المستخدم المُستهدف (userId) — فحص permission لا يعني cross-user authorization |
| checkCallingOrSelfPermission | نفس السابق لكن يشمل حالة أن العملية الحالية هي نفسها system_server | استخدامه بدل النسخة العادية بالخطأ قد يفتح ثغرة حين لا يكون هذا مقصودًا |
| Package ownership checks | أن `packageName` المُرسَل فعلاً يخص `callingUid` | الثقة بـ`packageName` كنص خام بدون التحقق من ملكيته لـUID المتصل |
| UID ownership checks | أن المورد المطلوب فعلاً يخص هذا الـUID | مقارنة جزئية أو غير دقيقة لأرقام UID (مثل تجاهل appId مقابل userId) |
| Cross-user checks (enforceCrossUserPermission وما شابه) | أن المتصل مصرّح له بالعمل على userId مختلف عن userId الخاص به | غيابها تمامًا رغم وجود targetUserId كمعامل قادم من المتصل |
| AppOps checks | هل المستخدم سمح فعليًا وقت التشغيل (رغم منح الصلاحية) | الاعتماد فقط على Permission ونسيان AppOps تمامًا |
| Roles | صلاحيات مرتبطة بدور نظامي (مثل Default SMS app) | افتراض أن حامل الدور موثوق بالكامل لكل عملية دون تحقق إضافي |
| System / shell / root special cases | استثناءات مصرَّح بها للعمليات المميزة نفسها | توسيع الاستثناء عن طريق الخطأ ليشمل مسارات يصل إليها تطبيق عادي |

### 6.2 تعريف Security Invariant

الـSecurity Invariant هو قاعدة عامة يجب ألا تُنتهك أبدًا، مستقلة عن أي CVE بعينه. هذا هو المفهوم المركزي الذي سيحل محل حفظ الأنماط الفردية:

> **مثال Invariant:** *A caller must not perform an operation on behalf of another Android user without an explicit, verifiable cross-user authorization check performed before the caller's original identity is lost.*

سنبني مكتبة من 50 Invariant من هذا النوع في الفصل 9، مصنّفة حسب الفئة (UID, Package identity, Binder, Permissions, Cross-user, AppOps, Intents, PendingIntent, URI, Files, State, Race conditions, Privilege transitions). هذه المكتبة ستكون العمود الفقري لكل من: توليد الـDataset، وتصميم الـTaxonomy في الجزء الرابع، وبناء الـSecurity Facts Extractor في الجزء العاشر.

> **Definition of Done — الجزء الثاني:** أي شخص يعمل على المشروع (بشري أو مراجعة يدوية لعينات النموذج) يجب أن يستطيع، لأي method من AOSP، الإجابة بثقة عن: من المتصل؟ هل الهوية تتغير أثناء التنفيذ؟ هل هناك تحقق cross-user؟ هل هناك AppOps check منفصل عن الـpermission؟ لو الإجابة "لا أعرف" لأي سؤال، فهذا سبب كافٍ لتصنيف الحالة كـ`insufficient_context` لاحقًا بدل التخمين.

---

[← الجزء الأول](./part-01-project-definition.md) · [الفهرس](./README.md) · [الجزء الثالث →](./part-03-threat-modeling.md)
