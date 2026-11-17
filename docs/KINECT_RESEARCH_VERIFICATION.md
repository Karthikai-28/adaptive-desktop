# Kinect research: what was checked, and what it changed

The research in `kinect/` (`Kinect_Complete_Documentation.md`, the scanner package's docs, and
`deep-research-report.md`) was written by ChatGPT Deep Research on November 17, 2026. This file
records a second, independent check of its claims, made on November 18, 2026, before anything
was built on them: a web search against primary sources (two independent sources where they
exist), and, where the claim is about this hardware, a measurement on the Kinect itself.

What was built from it: [KINECT_MOTION.md](KINECT_MOTION.md).

**Statuses**

| Status | Meaning |
| --- | --- |
| Confirmed | Two independent sources agree (or one primary source plus a measurement here) |
| Confirmed, one source | Only a primary source was reachable |
| Measured | Checked on this machine's Kinect |
| Corrected | The claim is wrong or overstated; the correction is what the code follows |
| Unverified | No source found or the source blocks checking; nothing here depends on it |
| Outdated | True when written somewhere, not now |

## What did not arrive

`deep-research-report.md` describes a **582-line fitness chapter** and a **v0.2.0 codebase**
(`fitness.py`, `fitness_store.py`, `fitness_cli.py`, a synthetic curl fixture). Both were links
into ChatGPT's sandbox (`sandbox:/mnt/data/...`); neither file is on this machine or in the repo,
and `Kinect_Complete_Documentation.md` in the repo is the earlier version without that chapter.
Every feature the summary lists was therefore implemented here from scratch (see the last
section), not copied. To compare against ChatGPT's own chapter, download it from that chat and
put it in `kinect/`.

## Hardware: the Kinect v1 on this machine

| Claim (research) | Status | Evidence |
| --- | --- | --- |
| Field of view ~57° x 43° | Confirmed + Measured | MSDN Magazine (2012) and the U. Arkansas Kinect hardware page give 57° x 43°; this device's factory projection (libfreenect `camera_to_world`) is fx = fy = 575.816 px at 640 x 480: a **58.1° x 45.3°** pixel field of view |
| Tilt motor ±27° | Confirmed | Same two sources |
| Range "~1.2–3.5 m sweet spot" | Corrected | 1.2–3.5 m is the Xbox software's practical limit; tracking extends ~0.7–6 m (Packt; U. Arkansas). Depth reads 0.5–4.5 m here ([KINECT.md](KINECT.md)); the play area used is 1.3–4.2 m |
| Random depth error grows from a few mm to ~4 cm at maximum range | Confirmed | Khoshelham & Oude Elberink, ISPRS 2011 and *Sensors* 12(2) 2012 abstracts. (Trade press says *resolution* falls quadratically with distance; the abstract does not say the *error* is quadratic) |
| Microsoft SDK 1.x: detects 6 people, full skeleton for 2, 20 joints | Confirmed | Microsoft Learn, Kinect 1.8 "Tracking Modes"; Packt *Kinect for Windows SDK Programming Guide* |
| Kinect v2: six full skeletons, 25 joints | Confirmed, one source | Microsoft "No bones about it" Kinect blog |
| libfreenect drives Kinect v1 on Linux but has no skeleton | Measured | The repo's own build (0.7.5) streams depth here; skeletons come from elsewhere (below) |
| SDK 1.8 needs Windows 7/8/8.1 and a dedicated USB 2.0 bus | Confirmed with a nuance | The download page lists 8.1; the official requirements page lists only 7 and 8. Irrelevant on Ubuntu |
| This Kinect's mount | Measured | The floor fit puts the Kinect **0.79 m above the floor, level** (tilt −0.6°) on Nov 18; the planned TV mount is ~1.9 m. Re-check after mounting (Kinect Room's coverage map) |

## How Microsoft did it, and what was taken from it

| Claim | Status | Evidence | Used here |
| --- | --- | --- | --- |
| Kinect skeleton tracking = per-pixel body-part classification on depth with a randomized decision forest trained on synthetic images, < 5 ms a frame on the Xbox 360 GPU | Confirmed | Shotton et al., CVPR 2011 (paper PDF); *Communications of the ACM* 2013 reprint | Not re-implemented (it needs Microsoft's training set). Instead: MediaPipe's pose model per person **fused with Kinect depth**, and, like Shotton's depth offset, each skin point pushed back by the limb's radius to the joint centre |
| The SDK marks joints Tracked / Inferred / NotTracked | Confirmed (same SDK docs) | Every joint here has the same three states, drawn solid / hollow on screen, and nothing is coached from a joint that was not seen |
| Nike+ Kinect Training (2012): a fitness assessment, real-time form feedback, a programme that adapts, re-assessment every four weeks | Confirmed | Microsoft News (June 2012); Game Informer and Engadget reviews | Kinect Fitness's **Fitness check** (retest after 28 days, compared with your own last check) and spoken form cues |
| Xbox Fitness (2013): heart rate from the camera, muscle map, energy meter | Confirmed as marketed; no accuracy data; Kinect v2 only; closed July 1, 2017 | Xbox Wire (Sept 2013); Wikipedia | Not possible on a Kinect v1 (no time-of-flight / active-IR heart rate). Not claimed. Calories are labelled estimates |

## Fitness evidence

| Claim | Status | Evidence | Effect on the code |
| --- | --- | --- | --- |
| Kinect squat hip/knee angles within 5° of marker capture | **Corrected** | No source found for "< 5°". Azure Kinect vs markers (Jo et al., *Sensors* 2022): moderate-to-excellent when the joint is visible, **poor when hidden**; older Kinect vs Vicon knee flexion: 13.2% mean difference with wide spread (TCD 2016) | Angles are trend signals, not measurements; coaching stops when required joints are not seen ("insufficient evidence") |
| AMIE: 99% exercise recognition, 73% mistake recognition | Confirmed | KU Leuven Lirias record; ECML-PKDD 2018 poster and code (ML-KULeuven/amie): 10 subjects, 1,790 reps, squat / forward lunge / side lunge | Recognising *which* exercise is easy; recognising *faults* is not. The cue set follows AMIE's squat faults (knee valgus, forward trunk lean) and is tested on synthetic faults |
| 2025 RCT: 60 pre-frail older adults, Kinect aerobic dance vs video, 8 weeks | Confirmed | *Frontiers in Public Health* 2025 (PMC12188645), NCT06216236 (30 min, 3x a week, assessor-blinded) | Supports exergaming for adherence; the Arcade and the challenge mode |
| Calories: MET x 3.5 x kg / 200 per minute | Confirmed | ACSM metabolic equations (Texas Tech HFI notes); Healthline / ACE worked example | `training.kcal`, checked: 8 MET, 73 kg, 1 min = 10.2 kcal |
| MET values (2024 Adult Compendium) | Confirmed | pacompendium.com conditioning-exercise table; PMC listing of the 2024 Compendium: 02020 vigorous calisthenics **7.5** (not 8.0 as older tables say), 02022 3.8, 02024 2.8, 02052 squat/deadlift 5.0, 02054 resistance 3.5, 02056 3.0, 02057 6.5, 02101 stretching 2.3 | Each exercise cites its code; high knees, punches, wall sit and balance have no entry and are marked **proxy** |
| A dumbbell's weight cannot be seen; Tempo recognises only its own weights | Confirmed | Tempo support "Weight Recognition FAQs" (current: Tempo dumbbells/plates only, up to 65 lb extended); research reasoning | Load is only ever recorded from you (registered equipment or a typed weight), never from the camera |
| Nuitrack supports Kinect v1 on Linux | Partly | Nuitrack lists Kinect v1 and Linux, but Kinect v1 skeletons on Linux are not explicitly confirmed; proprietary licence | Not used |
| OpenNI + NiTE / OSCeleton give Kinect v1 skeletons on Linux | Confirmed as legacy | ROS answers, KDAB guide, 2025 blog; NiTE is closed and unmaintained, needs a "psi" pose, two people | Not used; MediaPipe + depth instead (six people, no calibration pose) |
| MediaPipe Pose: 33 landmarks, metric world landmarks around the hips | Confirmed | Google AI Edge Pose Landmarker guide; MediaPipe GitHub docs. Axis orientation is undocumented (Google forum) | The model's skeleton is anchored on the depth-measured torso, so its axes do not matter for position |
| Depth-camera pointing control of Home Assistant: 96% accuracy, 26.67 ms (IEEE 2026) | **Unverified** | IEEE Xplore refuses automated access (HTTP 418); no other source found | Nothing depends on it. Pointing is implemented with the eye-to-wrist ray and tested on synthetic geometry |

## Platforms, PS5, and the PC games

| Claim | Status | Evidence | Effect |
| --- | --- | --- | --- |
| Azure Kinect SDK retired August 2024; hardware end of production August 2023 | Confirmed (date 16th vs 17th differs between sources) | Microsoft lifecycle page; SDK repo change; press | The Kinect v1 + open software is the path |
| ViGEmBus is retired and archived | Confirmed | GitHub archive (Nov 2, 2023); nefarius "End of Life" page | Kinect Pad uses Linux's own uinput instead |
| chiaki-ng: maintained open-source PS4/PS5 Remote Play, Linux, controller mapping; not Sony-endorsed | Confirmed | chiaki-ng project site; GamingOnLinux (2024, 2025). Sony's official Remote Play is Windows/macOS only | Kinect Pad's virtual gamepad works with chiaki-ng: the PS5 route here is PC → chiaki-ng → PS5, unofficial, with Remote Play latency on top |
| A PS5 has no Kinect support | Not re-checked (consistent with Sony's USB guide in the research) | — | No direct PS5 integration attempted |
| FAAST turns body movement into keyboard/mouse; World of Warcraft demo | Confirmed | USC ICT paper; Tom's Hardware, NBC (2010) | Windows-only; its idea is Kinect Pad on Linux |
| Free Riders Recompiled: native PC port with Kinect v1 input, bring your own game data | Confirmed | GitHub releases (v0.2.0 "Camera motion input"); release notes require your own disc image | Windows and copyrighted assets: not integrated |
| RunStickmanRun, KinectWare, Flappy Bird 3D / Space Walk, JD-Kinect, KinectHeadTrackerV2, the Unity Kinect v1 fork | Not re-checked one by one (GitHub cannot be fetched from here) | — | All need Windows + Kinect SDK 1.8 (+ Unity): none run on this Ubuntu machine. Kinect Arcade's games are original, built on the same body signals |
| Femto Bolt $418, out of stock | Outdated | Resellers list $559–609 (DigiKey, others); the K4A wrapper and Azure body tracking support are confirmed by Orbbec's docs | Not relevant: the build targets the Kinect v1 you own |

## Scanning

| Claim | Status | Evidence | Effect |
| --- | --- | --- | --- |
| A fixed camera measures only the surfaces it sees | Measured | Live snapshot here: `"scope": "observed_surfaces_only"`; the mesh is open | The scanner says so in every report |
| ReconstructMe's selfie mode scales the model to 20 cm; free for non-commercial use | Confirmed (scaling, official FAQ); free use dated 2015 | reconstructme.net FAQ and selfie guide; CG Press 2015 | Windows only; noted |
| Skanect is "retired" | Partly | Structure's support page confirms Kinect v1 is an unofficial, unsupported sensor; the word "retired" was not found | Not used |
| RecFusion supports Kinect v1, €199, evaluation cannot export | Unverified | No source reached | Not used |
| The delivered scanner: 38 tests passed, the Open3D test skipped | **Corrected** | Run here with Open3D 0.20: the skipped test **failed**: `ScalableTSDFVolume` returns no surface on this Open3D (even for a flat wall). Fixed with a uniform-volume fallback; now **39 passed, 0 skipped** | `kinect/kinect-v1-ubuntu-scanner/docs/VALIDATION.md` addendum |
| Snapshot, factory calibration, exports work on a real Kinect | Measured | 90,529 points, 36,433-triangle mesh, PLY/PCD/XYZ/OBJ/STL, directly and through the hub | `scripts/kinect-scan.sh` |

## From the fitness summary: implemented

Every feature named in `deep-research-report.md`, written here (not the unreceived v0.2.0 code):

| Summary item | Where |
| --- | --- |
| 3D joint angles | `skeleton.py` (knee, hip, elbow, abduction, trunk lean, body line), on depth-fused joints |
| Squat and curl state machines | `exercises.py` `Machine`: one rest → work → rest machine for 10 repeated exercises, plus 4 holds |
| Bilateral asymmetry, trunk deviation | Per-side counts and balance, "Sit evenly", "Press both arms evenly", trunk-lean cues |
| ROM, tempo, balance, posture | Depth reached per rep, seconds down/up, sway in cm on one leg, posture from the hub |
| Calories with an explicit warning | `training.kcal`, shown as "about … kcal, estimated" |
| Trusted dumbbell load resolution | `training.resolve_load`: sensor > confirmed > catalog > tag > label; never the camera |
| Training volume, progressive overload | `training.volume`, `training.progression` (double progression) |
| Local SQLite users / sessions / sets | `store.py` (`~/.local/share/adaptive-desktop/fitness.db`, mode 600, results only) |
| Offline skeleton replay | `sim.py` sessions drive `exercises.Tracker` in `scripts/verify-kinect-motion.py` |
| "Insufficient evidence" state | `Tracker`: a required joint missing or too few seen → no count, no coaching, and it says why |
| Acceptance protocol: rep ground truth, cue precision, latency percentiles, joint confidence, identity swaps, known weight | Synthetic ground truth in the checks (exact counts under 3 cm noise and 25% dropped frames; each fault cue on its fault); live latency p50/p95 on screen; tracked/inferred per joint; re-identification tested; weights only from you. Live ground truth with people is still to do ([KINECT_MOTION.md](KINECT_MOTION.md), "Not yet verified live") |
| Privacy, accessibility, safety | Results-only history; big gestures; a play area and spacing check that pause the player who is unsafe |

## Sources used in this check

- Microsoft Learn, Kinect 1.8 Tracking Modes: https://learn.microsoft.com/en-us/previous-versions/windows/kinect-1.8/hh973077(v=ieb.10)
- Kinect 1.8 system requirements: https://learn.microsoft.com/en-us/previous-versions/windows/kinect-1.8/hh855359(v=ieb.10)
- Kinect v2 skeletal tracking: https://docs.microsoft.com/en-us/archive/blogs/kinectforwindows/no-bones-about-it-kinect-for-windows-v2-skeletal-tracking-vastly-better
- Shotton et al. 2011: https://people.cs.pitt.edu/~chang/231/y17/PoseRecognition.pdf ; CACM 2013: https://cacmb4.acm.org/magazines/2013/1/158776-real-time-human-pose-recognition-in-parts-from-single-depth-images
- Kinect hardware: https://gmv.cast.uark.edu/scanning/hardware/microsoft-kinect-resourceshardware/
- Khoshelham & Oude Elberink: https://isprs-archives.copernicus.org/articles/XXXVIII-5-W12/133/2011/ ; https://api.crossref.org/works/10.3390%2FS120201437
- Nike+ Kinect Training: https://news.microsoft.com/source/2012/06/05/xbox-and-nike-team-up-to-revolutionize-fitness-at-home/ ; https://www.engadget.com/2012/06/04/nike-allies-with-xbox-360-for-nike-kinect-training-real-time-f/
- Xbox Fitness: https://news.xbox.com/en-us/2013/09/27/xbox-one-xbox-fitness-unveiled/ ; https://en.wikipedia.org/wiki/Xbox_Fitness
- Jo et al. 2022 (Azure Kinect vs markers): https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9785788/ ; Kinect vs Vicon knee flexion: https://tara.tcd.ie/bitstream/handle/2262/108521/j2016_GaitAndPosture_KneeFlexionKinectVsVicon_WithPageNumbers.pdf
- AMIE: https://lirias.kuleuven.be/retrieve/514399 ; https://tomdecroos.github.io/reports/amie-poster.pdf ; https://github.com/ML-KULeuven/amie
- Kinect aerobic dance RCT: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12188645/
- ACSM equations: https://www.depts.ttu.edu/ksm/_documents/grad/acsm_comps/6c-23-2013_HFI_Metabolic_Calculations.pdf ; https://www.healthline.com/health/what-are-mets
- 2024 Adult Compendium: https://pacompendium.com/conditioning-exercise/ ; https://pmc.ncbi.nlm.nih.gov/articles/PMC10818145/
- Tempo weight recognition: https://support.tempo.fit/support/solutions/articles/151000154718-weight-recognition-faqs
- MediaPipe Pose Landmarker: https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/web_js ; https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/pose.md
- Nuitrack SDK: https://www.github.com/3DiVi/nuitrack-sdk ; Linux Kinect skeletons: https://smbct.github.io/blog/kinect_tracking
- Azure Kinect lifecycle: https://learn.microsoft.com/en-us/lifecycle/products/azure-kinect-sdk
- ViGEm end of life: https://docs.nefarius.at/projects/ViGEm/End-of-Life/ ; https://github.com/nefarius/ViGEmBus
- chiaki-ng: https://streetpea.github.io/chiaki-ng ; https://gamingonlinux.com/2025/02/open-source-playstation-remote-play-client-chiaki-ng-gets-improved-controller-mapping
- FAAST: https://ict.usc.edu/pubs/Adapting%20user%20interfaces%20for%20gestural%20interaction%20with%20the%20%ef%ac%82exible%20action%20and%20articulated%20skeleton%20toolkit.pdf ; https://www.tomshardware.com/news/World-of-Warcraft-Kinect-FAAST-Evan-Suma-USC-Institute-for-Creative-Technologies,11856.html
- Free Riders Recompiled: https://newreleases.io/project/github/YuutaTsubasa/Free-Riders-Recompiled/release/v0.2.0
- Kinect SDK 1.8 download: https://www.microsoft.com/en-ca/download/details.aspx?id=40278
- Orbbec K4A wrapper: https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Using%20Orbbec%20SDK%20K4A%20Wrapper
- Skanect drivers: https://support.structure.io/article/374-what-sensor-drivers-should-i-install
- ReconstructMe selfie / scaling: https://www.reconstructme.net/qa_faqs/how-do-i-create-a-3d-selfie/ ; https://www.reconstructme.net/faq-category/scanning/
