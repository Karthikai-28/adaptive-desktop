# Kinect v1 Fitness Research Extension and Ubuntu Integration

## Research chapter

The existing Kinect documentation has been extended with a new **582-line fitness/exercise research chapter**, while retaining all previous gaming, scanning, Ubuntu, and implementation material. The updated document covers the fixed elevated living-room configuration, Linux acquisition through `libfreenect`, OpenNI/NiTE and OSCeleton legacy paths, Nuitrack, RGB-pose-plus-depth alternatives, exercise recognition, repetition counting, form scoring, joint angles, ROM, asymmetry, balance, posture, dumbbell tracking, workout history, progressive overload, calories, privacy, accessibility, safety, validation, engineering effort, and deployment architecture. `libfreenect` itself provides Kinect v1 RGB/depth acquisition on Linux but not the production skeleton layer, so the architecture deliberately separates raw sensing from the skeleton provider. citeturn876886view0turn876886view1turn876886view3

[**Updated complete Kinect documentation — Markdown**](sandbox:/mnt/data/Kinect_Complete_Documentation.md)

The research also separates capabilities that have actually been demonstrated from recommendations. For example, Kinect research has shown useful squat joint-angle and postural-control measurements under specific study conditions, but those results do not justify treating every home exercise metric as clinically accurate. A squat study reported average absolute Kinect-versus-marker differences below 5° for the examined hip/knee angles, while postural-control research found strong agreement for many measurements but also systematic biases in some outcomes. citeturn876886view9turn876886view10

## Weight, calories, and form tracking

The documentation makes one important product constraint explicit: **an arbitrary dumbbell's kilograms cannot be reliably inferred from Kinect RGB/depth geometry alone**. Shape does not determine material density or internal loading. The proposed implementation therefore ranks known weight sources such as an external smart sensor, user-confirmed value, known-equipment catalog, RFID/BLE identity, or confirmed OCR label; otherwise it returns the weight as unknown. Commercial systems follow similar bounded approaches: Tempo documents weight recognition only for supported Tempo equipment/configurations rather than claiming universal visual mass measurement. citeturn142880view4turn142880view3

Calories are similarly treated as **estimates rather than Kinect measurements**. The implementation supports a MET-based estimate using body mass, activity intensity, and duration, while the research chapter explains why heart rate or individually validated physiological models would be needed for stronger estimates. The current Compendium assigns substantially different MET values to different resistance activities, and experimental Kinect research has investigated energy-expenditure prediction rather than direct calorimetry. citeturn142880view0turn142880view1

## Existing fitness systems and reusable work

The chapter maps reusable open-source and academic work including `libfreenect`, `OpenNI2-FreenectDriver`, OSCeleton, Nuitrack, MediaPipe, AMIE, MotionTalk, SmartCrutch, UBD-Kinect, rehabilitation assessment projects, dumbbell/MediaPipe trackers, and legacy Kinect skeleton projects. It explicitly marks Kinect-v2-only repositories and datasets so they are not mistakenly treated as Kinect-v1 Ubuntu solutions. AMIE, for example, reported 99% exercise-type classification and 73% mistake classification in its ten-person squat/lunge study, which also illustrates that recognizing an exercise is substantially easier than robustly identifying incorrect form. citeturn876886view6

Historical and modern commercial systems are used as feature references rather than reusable code. Nike+ Kinect Training demonstrated personalized training and real-time movement feedback; Kinect PlayFit aggregated activity history and calorie estimates; Your Shape added feedback and floor-exercise tracking; Kinect Sports research showed that metabolic intensity varies substantially by activity. Modern Tempo, Tonal, and Peloton systems add concepts such as rep tracking, equipment/load history, ROM, strength progression, form feedback, and smart resistance/equipment integration. citeturn142880view5turn142880view6turn627519search0turn627519search8turn142880view7turn142880view11

## Ubuntu codebase integration

The accompanying codebase is now **version 0.2.0** and includes the fitness layer rather than documentation alone. The new `fitness.py` provides 3-D joint-angle calculations, reference squat and curl state machines, bilateral-asymmetry and trunk-deviation metrics, calorie estimation with an explicit warning, trusted dumbbell-load resolution, and training-volume calculations. `fitness_store.py` adds local SQLite users/workout sessions/sets, while `fitness_cli.py` adds an offline normalized-skeleton replay command. A synthetic curl fixture and example output are also included.

[**Updated Kinect v1 Ubuntu scanner + fitness codebase v0.2.0**](sandbox:/mnt/data/kinect-v1-ubuntu-scanner-fitness-v0.2.0.zip)

The fitness code deliberately consumes a provider-independent 3-D skeleton instead of pretending that `libfreenect` supplies skeletal tracking. That allows the same exercise engine to receive joints from NiTE/OSCeleton, Nuitrack, or an RGB landmark model combined with Kinect depth. This distinction is especially important on Linux because Kinect v1 raw acquisition and skeleton estimation are separate problems. citeturn876886view0turn876886view2turn876886view5turn876886view3

## Validation and deployment boundary

The updated project passes **42 automated tests with one optional Open3D test skipped** in the available execution environment. The new tests cover joint-angle calculations, curl repetition state transitions, conservative load handling, training-volume arithmetic, and calorie-estimate semantics in addition to the existing scanner/geometry tests. A physical Kinect was not available in this environment, so the documentation explicitly does **not** claim that live Ubuntu skeleton tracking, the 6–7 ft mount, real exercise recognition, or real-world form-scoring accuracy has already been validated.

That physical validation is particularly important for the proposed elevated mount. Kinect v1 has approximately a 57° × 43° field of view and a relatively constrained structured-light working volume, while Microsoft historically documented full-body visibility and occlusion as important skeleton-tracking considerations. Strong ambient infrared, self-occlusion from dumbbells, floor exercises, loose clothing, multi-person interference, and interpolated joints can all degrade the result. citeturn142880view13turn142880view14turn142880view15

The research therefore includes an objective acceptance protocol: annotated-video rep ground truth, per-form-cue precision/recall, joint-angle comparison with a stronger reference system where accuracy claims matter, latency percentiles, joint-confidence availability, identity-swap testing, known-weight verification, and an explicit **“insufficient evidence”** state so tracking failures do not become incorrect coaching.

[**Updated codebase under the original ZIP filename as well**](sandbox:/mnt/data/kinect-v1-ubuntu-scanner.zip)