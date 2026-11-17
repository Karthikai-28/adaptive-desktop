iturn184767image2turn184767image0turn184767image3turn184767image1

# Kinect-Like Depth Sensors for a Multi-Person Living Room: Productivity, Gaming, PS5 Integration, and an Engineering Roadmap

As of **November 17, 2026**, the most important conclusion is that the original Kinect idea is still very useful, but the best modern implementation is no longer “buy a Kinect and plug it into a console.” Microsoft has discontinued Kinect v1/v2, Azure Kinect hardware has been discontinued, and the Azure Kinect SDK reached retirement on August 17, 2024; Microsoft’s sensor repository is archived. The most practical successor for a new build is currently **Orbbec Femto Bolt**, because it reproduces Azure Kinect’s Microsoft iToF depth modes and can run applications written against the Azure Kinect API through Orbbec’s K4A wrapper. RealSense D455/D555, Orbbec Gemini 335, Luxonis OAK-D Pro, and stereo cameras such as ZED 2i are viable alternatives, but they require more of your own pose-tracking/software stack. citeturn632532search0turn632532search1turn632532search2turn897579search0turn897579search5

For your specific room—sensor roughly **6–7 ft / 1.83–2.13 m above the floor, above the television, facing into the room, with several people potentially present**—a Kinect-style system is technically practical. The main design constraint is not raw depth quality; it is maintaining unobstructed views of hands, legs, and torsos when people overlap. A single high-mounted front sensor works well for one to three separated users and can often detect four or more, but a second camera from an oblique angle becomes far more valuable once people stand behind one another, cross paths, play close-contact games, sit on sofas, or use furniture. Orbbec explicitly cites filling occlusion zones as a reason to deploy synchronized multiple depth cameras. citeturn897579search2turn980399search5

## What the hardware can actually do in your room

The sensor generations differ much more than their similar appearance suggests. Kinect v1 used structured infrared light and offered roughly a 57° × 43° depth field of view with 20-joint skeletal models; Kinect v2 moved to time-of-flight sensing, widened depth FOV to roughly 70° × 60°, increased the skeleton to 25 joints, and could output whole skeletons for up to six people. Azure Kinect/Femto Bolt moves to a 1-MP time-of-flight depth imager, provides 32-joint Microsoft body tracking, and offers both a 75° × 65° NFOV and an unusually broad 120° × 120° WFOV. citeturn999613search0turn999613search9turn632532search9turn401293search1

| Sensor | Technology | Depth FOV | Useful depth range | Depth rate | Skeleton / pose situation | Status in 2026 |
|---|---|---:|---:|---:|---|---|
| Kinect v1 / Xbox 360 | Structured light | ~57° × 43° | ~1.2–3.5 m sweet spot | ~30 FPS | 20 joints; up to two fully tracked active players in the classic gaming model | Discontinued; cheap used hardware citeturn999613search7turn999613search12 |
| Kinect v2 / Xbox One | ToF | ~70° × 60° | ~0.5–4.5 m | 30 FPS | 25 joints; up to six full bodies | Discontinued, but still useful on PC with legacy SDK/libfreenect2 citeturn999613search42turn326238search1 |
| Azure Kinect DK | iToF | 75° × 65° NFOV; 120° × 120° WFOV | 0.25–5.46 m depending mode | Up to 30 FPS | 32 joints, multiple people; practical body count constrained by compute | Hardware and SDK EOL; used only citeturn999613search8turn632532search0turn980399search2 |
| **Orbbec Femto Bolt** | Microsoft-derived iToF | 75° × 65° / 120° × 120° | 0.25–5.46 m | Up to 30 FPS | Orbbec skeleton SDK or Microsoft Azure body tracker through K4A wrapper | **Best Kinect-like migration path** citeturn401293search3turn897579search0 |
| Orbbec Gemini 335 | Active/passive stereo | 90° × 65° | 0.10–20 m+, optimum ~0.26–3 m | 1280×800 @ 30 FPS | Requires Orbbec/custom pose pipeline | Current, inexpensive, strong general CV choice citeturn350229search0turn350229search1 |
| RealSense D455 | Stereo | ~87° × 58° | ideal ~0.6–6 m | Up to 90 FPS depth | No Kinect-equivalent integrated Microsoft skeleton API; use external pose stack/OpenNI/NiTE/custom | Current citeturn401293search11turn897579search18 |
| RealSense D555 | Stereo, PoE | 87° × 58° | ideal ~0.6–6 m | Up to 90 FPS | Same general software model as RealSense SDK 2.0 | Current, good remote-placement option citeturn350229search4turn350229search8 |
| Luxonis OAK-D Pro | Active stereo + onboard AI | ~80° × 55° stereo cameras | ideal ~0.7–12 m | Sensor-dependent | Run neural pose models on/through DepthAI | Current; attractive for embedded AI citeturn350229search2turn350229search3 |

For your mounting height, **Femto Bolt NFOV unbinned at 640×576/30 FPS is the mode I would start with**. Its documented range is 0.5–3.86 m and FOV is 75° × 65°; NFOV binned extends the specified range to 5.46 m but reduces depth resolution to 320×288. WFOV gives a spectacular 120° × 120°, but at 30 FPS its binned operating range is only about 2.88 m. citeturn401293search1turn897579search25

At a 3 m subject distance, a 75° horizontal FOV spans approximately **4.6 m of room width**; at 4 m it spans about **6.1 m**. Those are geometric calculations from the documented 75° FOV, so an NFOV sensor above a TV can already cover a normal living-room play zone without needing the 120° mode. The wide mode becomes useful if people stand very close to the TV or if the room is unusually wide. citeturn401293search1

A good starting geometry is therefore:

```text
Side view

                 Femto Bolt / depth camera
 TV top                  [●]   ≈ 1.9–2.1 m high
                          \
                           \  ≈ 10–15° downward pitch
                            \
                             \
         1.8 m       2.5 m       3.5 m        4.5 m
 floor ───P1────────────P2────────────P3────────────P4─────────

              Preferred primary interaction area
                    ≈ 1.8–3.8 m
```

With a 65° vertical NFOV, mounting around 2 m and pitching the optical axis downward around **10–15°** is a sensible first calibration point: it provides enough downward coverage to retain feet at normal play distances without turning the camera into an overhead/top-down view. That pitch is an engineering recommendation rather than a Microsoft-prescribed value; Microsoft did not publish one universal “optimal height,” and its own guidance notes that lighting, obstruction, body height and scene conditions all affect tracking. Community reports also show that tilted-camera coordinates must be transformed into your room/floor frame if you want intuitive gesture directions. citeturn980399search3turn980399search10turn980399search11

I would **not mount the sensor on the ceiling pointing steeply downward** if your primary goal is skeletal gaming. Body trackers work best when the camera sees recognizable frontal or three-quarter human silhouettes. Research on Kinect placement repeatedly finds that sensor position and self-occlusion strongly influence joint accuracy, and an Azure Kinect posture study found its most stable results in that experiment at roughly 1.6–2.2 m camera-to-person distance. citeturn501679search7turn980399search7

For one player, one camera is enough. For two players, one Femto Bolt/Kinect v2 is generally comfortable if they remain side-by-side. For three to four active people, widen the spacing and avoid one person standing directly behind another. For four-plus users doing aggressive movement, dancing, or party games, **two cameras at roughly 30–60° relative viewpoints** are a much more robust architecture than trying to solve occlusion algorithmically. Femto Bolt supports hardware synchronization through its sync port and multiple devices on one host if USB/compute resources permit. citeturn897579search2turn897579search9

Lighting is usually less problematic for ToF than ordinary RGB vision indoors, but direct sunlight and strong IR contamination remain enemies of infrared depth systems. Kinect v2 measurements have been shown to degrade under direct sunlight, and Azure Kinect accuracy studies intentionally block direct sun when making precision measurements. Stereo alternatives such as RealSense can work over longer distances but themselves depend on texture/IR projection and lighting conditions. citeturn999613search19turn980399search5turn401293search30

Latency is also important for games. Most Kinect-class depth pipelines run at 30 FPS, meaning a new depth frame arrives every 33.3 ms before pose inference, filtering and game logic are considered. Real Azure Kinect systems have sustained near-30-FPS body tracking on GPUs such as an RTX 2060, although Microsoft community reports also document configurations with noticeable tracker delay. For a responsive game, you should treat latency as an end-to-end engineering metric rather than “camera FPS”: timestamp capture, skeleton output, gesture recognition, virtual-controller output and display response separately. citeturn169073search1turn169073search7

## Games and entertainment: what you can play versus what you must build

There are two completely different ecosystems here: **legacy Kinect games**, which are finished commercial experiences designed for Xbox 360/Xbox One hardware, and **new PC experiences**, where a depth camera becomes an input device for software you create or adapt.

The original Kinect game library is still the best proof of what this interaction model can accomplish. Xbox’s Kinect launch lineup included Kinect Adventures, Kinect Sports, Kinectimals, Kinect Joy Ride and many others; Kinect Joy Ride was explicitly a controller-free kart racer. Dance Central was a full-body tracked dance game. Kinect Sports Rivals on Xbox One included wake racing, climbing, tennis, bowling, soccer and target shooting and supported two-to-four-player local multiplayer. citeturn445381search18turn445381search19turn445381search24turn445381search0

| Experience | Interaction | Ready to play? | Best way to reproduce today |
|---|---|---|---|
| **Kinect Joy Ride** | Hold imaginary steering wheel, steer with arms/body | Yes, but on Xbox 360 + Kinect | Legacy Xbox 360 hardware; or build similar PC control mapping citeturn445381search19 |
| **Forza Motorsport 4 Kinect features** | Kinect-enhanced automotive interaction alongside traditional controls | Legacy Xbox 360 | Legacy hardware only for authentic implementation citeturn445381search36 |
| **Kinect Sports / Sports Rivals** | Bowling, tennis, soccer, climbing, wake racing, shooting | Yes on original supported consoles | Xbox One + Kinect v2 for Rivals citeturn445381search0 |
| **Dance Central / Spotlight** | Full-body choreography recognition | Yes on supported Xbox hardware | Kinect v1/v2 legacy Xbox setup citeturn445381search5turn445381search24 |
| **Kinect Adventures** | Jumping, leaning, dodging, whole-body interaction | Legacy Xbox 360 | Xbox 360 Kinect bundle/software citeturn445381search22 |
| **Kinectimals** | Reach, gesture and interact with virtual animals | Legacy Xbox 360 | Original console/sensor citeturn445381search49 |
| **Tiger Woods PGA Tour 13** | Golf swing/body motion | Legacy Kinect integration | Xbox 360 setup citeturn445381search40 |
| **Fable: The Journey** | Arm/gesture actions | Legacy Kinect | Xbox 360 setup citeturn445381search40 |
| **RoomAlive-style games** | Touch walls, shoot, stomp, dodge, steer projected objects | Research prototype / custom | PC + one or more depth cameras + projector(s) citeturn475468search0turn475468search2 |
| **Point-cloud avatar / volumetric mirror** | Real-time 3D reconstruction of players | Custom | Unity/Unreal + RGB-D point cloud pipeline citeturn326238search4turn326238search8 |
| **Virtual wall/table touch** | Hands become touch points on ordinary surfaces | Custom | Calibrated depth camera + surface plane detection citeturn475468search6 |

For your **car-game idea**, the easiest convincing prototype is not to begin with skeleton-to-PS5 integration. Begin on a PC: map shoulder midpoint to steering center, calculate the vector between hands as an imaginary steering wheel, derive steering angle from that vector, use forward hand displacement or hand state for throttle/brake, and emit an XInput joystick axis. A second mode can use hip lateral displacement as steering so children or casual players do not need to hold their arms up continuously. Kinect Joy Ride demonstrates that the interaction concept is viable; your modern implementation can use significantly richer skeleton data. citeturn445381search19turn632532search9

Other living-room games that map unusually well to one overhead-TV sensor include boxing, skiing, snowboard lean, goalkeeper, penalty kicks, cricket/baseball batting, tennis, archery, rhythm/dance, “floor is lava,” obstacle dodging, balance challenges, Simon Says, charades recognition, freeze dance, cooperative pose matching, virtual sword fighting, fitness races, and asymmetric multiplayer where one person’s arms steer while another person’s stance controls acceleration. These are custom applications, but they use exactly the body/joint information exposed by Kinect-class trackers rather than requiring exotic point-cloud algorithms. Microsoft’s Body Tracking SDK returns independently identified multi-person skeletons and 32 joints per person for Azure Kinect-compatible systems. citeturn632532search9turn897579search5

The more unusual experiences come from ignoring the skeleton entirely and using the **point cloud**. You can make players appear as particles, melt their silhouettes into the walls, create trails and spatial echoes, erase portions of the room, make virtual objects collide with people, reveal invisible objects as people walk around them, create volumetric freeze frames, or render one person from another viewpoint. Microsoft’s RoomAlive prototype demonstrated room-scale projected games in which users could touch, shoot, stomp, dodge and steer projected content, while MirageTable and HoloDesk demonstrated freehand interaction between depth-captured physical objects and virtual geometry. citeturn475468search0turn475468search4turn475468search5

RoomAlive is especially relevant to your ceiling/high-TV idea. Microsoft released an open-source toolkit that calibrates multiple Kinect/projector pairs and streams depth data into Unity; their large demonstration used six Kinect cameras and six projectors. You do not need six units for a living room—a single projector plus one depth camera can make an interactive wall/floor—but the research establishes that a complete room can be treated as a playable surface. citeturn475468search1turn475468search2

## Day-to-day productivity: what is genuinely useful

The strongest productivity use is **ambient interaction**, where the system does something useful because it knows where people are and what they are doing without requiring phones, remotes, keyboards or wearable trackers.

A 2026 IEEE home/building interaction project is particularly relevant: it used depth-camera pointing gestures to control Home Assistant devices, reporting **96% average gesture accuracy and 26.67 ms average recognition latency** in its experiment, while emphasizing that depth-only imagery offers more privacy than ordinary RGB video. That is a credible modern implementation of “point at the lamp / point at the fan / gesture to change a device” rather than an old Kinect novelty. citeturn501679search9

Ergonomics is another genuinely useful category. Kinect-based research has demonstrated automatic extraction of joint geometry for RULA-style posture assessment, while later Azure Kinect work validated a system for screening shoulder imbalance, pelvic tilt, forward head, scoliosis and related static posture characteristics against optical motion capture. These systems are not medical diagnostic replacements, but the evidence is substantially stronger than for novelty gesture controls. citeturn501679search7turn501679search6

For a home office, that translates into applications such as detecting prolonged slouching, desk-to-standing transitions, neck/shoulder posture, time spent sitting versus standing, repeated reaching patterns and exercise breaks. You should treat these as trend/behavioral signals rather than millimeter-accurate biomechanics because body tracking degrades under self-occlusion and unfavorable camera angles. citeturn501679search7turn501679search8

Exercise and rehabilitation have some of the deepest evidence. Kinect has been studied in home stroke exercise, chronic-stroke balance telerehabilitation, geriatric exergaming and long-duration home shoulder rehabilitation. A 2025 randomized study of 60 pre-frail older adults compared Kinect aerobic dance against video-based home exercise over eight weeks. These studies collectively support the idea that body-tracked exercise can improve adherence, give real-time feedback and make repetitive movement programs more engaging, although effect sizes and clinical populations vary. citeturn501679search0turn501679search1turn501679search2turn501679search3turn501679search5

Accessibility is another underused area. A depth camera can recognize large gestures for people who have difficulty manipulating small controls, detect pointing without speech, or combine movement with PlayStation’s own assist-controller functionality. Sony allows supported PS5 controllers to be paired as an assist controller so two controllers act as one, although this does **not** make a Kinect an officially supported PS5 controller. citeturn501679search9turn261907search5

Telepresence is more technically demanding but increasingly interesting. Microsoft’s Room2Room captured a person in 3D and projected a life-size representation into a remote space; a 2026 multi-view telepresence study fused three cameras into a point-cloud view for XR robot teleoperation and found that its mixed 3D/high-resolution representation performed better overall than the compared visualization modes in its 31-person study. citeturn475468search3turn501679academia10

A useful way to rank home applications is:

| Application | Practical value | Development effort | My assessment |
|---|---:|---:|---|
| Presence/occupancy and zone automation | High | Low | **Very worthwhile** |
| Gesture-triggered Home Assistant scenes | Medium-high | Medium | **Worthwhile if gestures are sparse and deliberate** |
| Exercise repetition/form feedback | High | Medium | **One of the best uses** |
| Posture/desk ergonomics | Medium-high | Medium | **Useful for trends and reminders** |
| Gaming/exergaming | High entertainment value | Medium | **Excellent fit** |
| Accessibility macro gestures | Potentially very high | Medium | **Strong targeted use case** |
| Automatic meeting framing / people counting | Medium | Low-medium | **Straightforward** |
| Volumetric telepresence | Medium | Very high | **Research/hobbyist rather than routine productivity** |
| Gesture-controlled mouse cursor | Low | Medium | **Mostly gimmicky** |
| Air typing / virtual keyboard | Low | High | **Usually worse than a physical keyboard or voice input** |
| Constant waving for lights/volume | Low | Low | **Novelty wears off quickly** |

The general lesson from fifteen years of Kinect experimentation is that **gesture works best for coarse spatial actions, not high-frequency precision input**. “Point at this,” “raise both hands,” “step into this zone,” “start my workout,” “pause,” “next track,” or “recognize this exercise repetition” are natural. Replacing a mouse with hand waving is tiring and less precise; depth-camera touch research itself notes that camera-based touch is less precise than direct capacitive sensing. citeturn475468search6

## PS5: what works, what does not, and the realistic architecture

A Kinect, Azure Kinect, Femto Bolt, RealSense or similar USB depth camera **does not have native PS5 game-input support**. Sony’s PS5 USB documentation enumerates supported controller classes, PS VR/VR2 hardware, the HD Camera and officially licensed specialty peripherals; Kinect-style generic RGB-D cameras are not part of the supported interface. Sony’s own PS5 HD Camera is primarily for 1080p capture/broadcast features, not Kinect-style skeletal gameplay. citeturn261907search0turn261907search1turn261907search8

So this architecture will **not** work:

```text
Kinect / Femto Bolt ──USB──> PS5 ──> arbitrary motion-controlled PS5 game
                         ✗
```

The console has no Kinect driver, no Azure/Orbbec SDK, no user-installable middleware layer and no standard mechanism by which an arbitrary USB depth sensor can expose skeletons to a PS5 title. Sony also states that PS5 games require supported PS5 controllers, while compatibility for third-party peripherals is device/title dependent. citeturn261907search1turn261907search7

The practical architecture is instead:

```text
                 USB 3
Depth camera ──────────────────> Gaming PC
                               │
                               │ depth -> skeleton
                               │ skeleton -> gestures
                               │ gestures -> virtual controller
                               │
             ┌─────────────────┴──────────────────┐
             │                                  │
      PC-native game                       Remote Play
      Unity / Unreal                       network stream
             │                                  │
             ▼                                  ▼
        TV / projector                        PS5
```

The **PC-native path is by far the better engineering choice**. You control the entire latency pipeline, can support multiple players, can run Unity or Unreal directly, and can map the sensor to XInput/keyboard/mouse or directly into game logic. Microsoft still publishes Azure Kinect samples including Unity body-tracking examples, while community projects provide Unity point-cloud rendering and Kinect/Azure wrappers. citeturn326238search2turn326238search3turn326238search4

For PS5, the legitimate supported bridge is **PS Remote Play**: Sony supports streaming a PS5 to Windows/macOS and expects a DualSense, DualSense Edge or DualShock 4 as the PC-side controller. Sony recommends at least 15 Mbps for a better Remote Play experience. citeturn261907search3turn261907search4

A depth-camera prototype can therefore recognize body movements on the PC and translate them into controller-like events, but getting those synthetic events accepted by the official Remote Play client is the weak point. Older Windows virtual-gamepad systems such as ViGEm could emulate Xbox 360 or DualShock 4 devices and were explicitly used for unsupported input devices and Remote Play, but **ViGEmBus itself is retired and its repository has been archived since 2023**. That makes it unsuitable as the foundation for a long-lived product. citeturn672751search4turn672751search5

An alternative experimental path is the open-source **chiaki-ng** Remote Play client. As of November 2026 it remains actively maintained, supports PS4/PS5 Remote Play across Windows, Linux and other platforms, and its current code includes controller-input transmission back to the console. It is explicitly not endorsed or certified by Sony, so firmware/protocol changes can break it and you should treat it as a research/hobbyist integration rather than a supported console interface. citeturn672751search0turn672751search2turn672751search3

The latency equation for that PS5 path is unfavorable:

```text
camera exposure/frame
+ USB transfer
+ body inference
+ gesture smoothing/classification
+ virtual-controller translation
+ Remote Play input transport
+ PS5 game processing
+ video encode on PS5
+ network transit
+ video decode/render on PC/TV
```

At 30-FPS depth capture alone, the sampling interval is 33.3 ms; the Remote Play route then adds networking, encode/decode and display delay on top. Sony does not publish a universal end-to-end Remote Play latency because it depends on network and client hardware, so any fixed “50 ms” or “100 ms” claim would be misleading. For bowling, fitness, dance, party or turn-based motion experiences it can be tolerable; for precision racing, fighting games or competitive shooters, the PC-native path is considerably more appropriate. citeturn169073search2turn261907search3

A sensible PS5 prototype is therefore:

1. Run a Femto Bolt/Kinect v2/Azure Kinect on a Windows PC and first confirm stable 30-FPS skeleton tracking.
2. Build a simple visual debug window showing skeleton, tracked ID, gesture state and controller output.
3. Map only three actions initially: left/right steering, throttle and brake.
4. Test those mappings against a **PC game first** using normal virtual-controller or keyboard input.
5. Measure camera-to-game-response latency with a 120/240-FPS phone video.
6. Only after the interaction feels good, test PS Remote Play.
7. Begin with a real DualSense attached and use your motion layer only for supplemental inputs if your middleware permits it.
8. If experimenting with chiaki-ng, keep the implementation isolated behind an input adapter so a Remote Play update does not force you to rewrite the tracking system.
9. Do not design a commercial product around undocumented PS5 controller emulation unless you obtain Sony licensing/support.

That architecture also gives you a useful fallback: the PS5 remains a normal PS5, while the PC becomes the room’s “spatial computer.”

## Open-source projects and maker ecosystem worth studying

For Kinect v1, **libfreenect** remains the canonical open-source driver stack and exposes RGB, depth, motor, accelerometer, LED and audio functions across Linux, macOS and Windows. Kinect v2 has **libfreenect2**, which supports RGB, IR, depth and RGB-depth registration. These are valuable if you want cheap hardware experiments without depending on Microsoft’s old Windows SDK. citeturn326238search0turn326238search1

For Azure Kinect/Femto Bolt, Microsoft’s **Azure-Kinect-Samples** repository remains an excellent reference even though the underlying Microsoft stack is archived. It contains Sensor SDK and Body Tracking SDK examples, including a Unity skeleton sample. Orbbec’s K4A wrapper is specifically designed to preserve compatibility with Azure Kinect applications on Femto Bolt. citeturn326238search3turn326238search2turn401293search12

For visual experimentation, **AzureKinectUnityFree** includes an environment point-cloud VFX demo, while **KinectCloud** can capture colored Azure Kinect point clouds and stream them to Unity. These give you a quick route to “digital ghost,” particles, volumetric avatar and room-deformation prototypes without first writing your own depth-to-XYZ conversion. citeturn326238search4turn326238search8

For projection, **Microsoft RoomAliveToolkit** is still one of the most instructive codebases because it covers projector-camera calibration, multiple Kinects and Unity integration. The independent KinectProjectorToolkit demonstrates body projection, background manipulation and even a simple game where falling polygons interact with a person on a wall. citeturn475468search2turn475468search9

For home automation, the modern pattern is to decouple perception from automation using **MQTT/Home Assistant**. One current open-source Home Assistant project recognizes hand gestures from camera frames and publishes them over MQTT so automations can react. It is RGB/MediaPipe-oriented rather than Kinect-specific, but the architecture—perception service → semantic gesture → MQTT event → automation—is exactly how I would structure your room controller. citeturn326238search7

A useful sign that the platform still attracts experimentation is that Kinect/Azure enthusiasts continue building dance and alternative tracking systems even after Microsoft stopped support; however, recent community projects that replace proprietary depth or body-tracking components should be treated as experimental until independently validated. citeturn169073reddit42

## Costs, privacy, safety, and the things most people overlook

Current pricing strongly favors starting with used Kinect hardware for proof-of-concept and buying a current camera only once you understand your interaction requirements. In November 2026, Orbbec’s official store lists Femto Bolt at **$418 but currently out of stock**; Gemini 335 is **$264**; RealSense lists D455 and D555 around **$499**; OAK-D Pro is around **$429**. Current U.S. used listings show Kinect v2 bundles around tens to roughly a hundred dollars, while Azure Kinect pricing is highly volatile because the product is discontinued—current listings commonly range into several hundred dollars despite some auctions having sold much lower. citeturn125361search0turn350229search1turn125361search1turn350229search5turn350229search2turn125361search5turn125361search3

| Budget | Hardware | What I would build |
|---|---|---|
| **$30–100 experiment** | Used Kinect v1/v2 + required PC adapter | Skeleton/gesture prototype, racing control, exercise counter |
| **$250–350 modern stereo** | Gemini 335 | Depth/point cloud + your own pose model; excellent CV experimentation |
| **$400–550 Kinect-successor** | Femto Bolt when available | Best route to Azure-Kinect-style skeleton tracking and Unity applications |
| **$500–800 embedded/AI** | OAK-D Pro or RealSense + capable GPU/mini-PC | Custom AI, high-rate depth, robotics-style pipelines |
| **$900–1,500+ serious room system** | Two depth cameras + PC + mounts | Reduced occlusion, 3–4+ player interaction |
| **$1,500+ immersive room** | Two-plus cameras + projector(s) | Interactive wall/floor, RoomAlive-like experiences |

The camera price is not the entire system cost. Body tracking is compute-heavy: Orbbec’s own Femto Bolt recommendations assume NFOV unbinned at 30 FPS while tracking five people, and a serious Unity application benefits from a discrete GPU. Cabling is also nontrivial: Femto Bolt is USB 3.2, and Orbbec warns that passive USB-C runs should generally remain short, recommending active cabling for longer installations. That matters when the camera is mounted permanently above a television and the PC is elsewhere. citeturn897579search7turn401293search1

Privacy deserves more attention than most Kinect hobby projects gave it. Depth-only processing reduces visual identity exposure compared with conventional RGB recording, but a point cloud still reveals room geometry, body dimensions, movement patterns, occupancy and potentially identifiable gait. Volumetric systems can also leak private objects through geometry even if RGB imagery is removed; recent research on privacy-preserving volumetric streaming explicitly treats depth as sensitive data. citeturn501679search9turn501679academia11

For a permanent living-room system I would therefore process frames locally, disable RGB unless an application needs it, retain only semantic events such as `person_2 / squat / repetition_14`, avoid continuous video storage, provide a physical sensor power switch or visible hardware indicator, and separate raw-camera services from Home Assistant/network services. Those are architectural recommendations based on the privacy properties of depth and volumetric capture rather than manufacturer requirements. citeturn501679academia11

Physical safety is equally important for games. Your system must know the playable floor polygon and reject actions near TVs, tables, fans, stairs and walls. A depth camera gives you enough room geometry to do something conventional console motion systems rarely did well: maintain a **dynamic safety envelope** and pause the game if a player approaches an obstacle or another player too closely. Room-scale projection research demonstrates that depth systems can build and continuously update spatial models of a room, although your safety implementation would need its own validation. citeturn475468search0turn475468search2

Another overlooked issue is **identity persistence**. Body trackers give each currently observed body an ID, but an ID is not a reliable permanent identity if a person leaves the field of view and returns. For multiplayer profiles you should re-associate players using starting zones, explicit “raise hand to join” enrollment, clothing appearance if RGB is enabled, or other session-level logic rather than trusting tracker IDs forever.

Furniture is a major source of failure. Sofas hide knees and feet, coffee tables create lower-body occlusion, and one human standing behind another can cause inferred rather than observed joint positions. Kinect ergonomics studies report exactly these kinds of problems in realistic scenes, and Microsoft/Orbbec multi-camera guidance treats occlusion as a primary reason for multiple viewpoints. citeturn501679search8turn897579search2

## Recommended architecture and implementation roadmap

For your requirements, my first-choice architecture is **one Femto Bolt above the television + Windows PC with an NVIDIA GPU + Unity**, with the mechanical mount deliberately designed so a second Femto Bolt or other depth camera can later be added at a side wall. If Femto Bolt availability remains poor, a used Azure Kinect is acceptable for prototyping but not attractive for a long-lived product because Microsoft hardware and SDK support have ended. A used Kinect v2 is even cheaper and can teach you nearly everything about game design before you spend money on the final sensor. citeturn125361search0turn632532search0turn632532search1

My decision matrix is:

| Criterion | Kinect v2 used | Azure Kinect used | Femto Bolt | Gemini 335 | RealSense D455 |
|---|---:|---:|---:|---:|---:|
| Cheap prototype | **5/5** | 3/5 | 2/5 | 4/5 | 2/5 |
| Built-in mature skeleton path | **4/5** | **5/5** | **5/5** | 2/5 | 2/5 |
| Multi-person living room | 4/5 | 5/5 | **5/5** | 4/5 | 4/5 |
| Wide FOV | 3/5 | **5/5** | **5/5** | 4/5 | 4/5 |
| Future software support | 1/5 | 1/5 | **5/5** | **5/5** | **5/5** |
| Low latency depth | 3/5 | 3/5 | 3/5 | 3/5 | **5/5** |
| Point-cloud experimentation | 4/5 | 5/5 | **5/5** | **5/5** | **5/5** |
| Kinect code compatibility | 2/5 | **5/5** | **5/5** | 1/5 | 1/5 |
| Best overall for your project | 3.5/5 | 4/5 | **5/5** | 4/5 | 4/5 |

The implementation should proceed in stages rather than trying to integrate games, PS5, automation and projection simultaneously.

**Prototype A: tracking validation.** Mount the camera around 1.9–2.1 m high, start at about 10–15° downward pitch, use NFOV unbinned/30 FPS, mark floor positions at approximately 1.5, 2, 2.5, 3, 3.5 and 4 m, and record skeleton confidence for one through four people. Test crossing, sitting, crouching, turning sideways, one person walking behind another, children versus adults and lights-on/lights-off conditions. The goal is to produce a room-specific tracking-quality heat map, not merely confirm that a skeleton appears. citeturn401293search1turn980399search10

**Prototype B: body-controlled racer.** Use Unity. Calculate steering from the angle between hands or shoulder/hip rotation, normalize it to −1…+1, add a dead zone and exponential/spline response, then apply temporal smoothing. Map throttle to one foot forward, hand extension, lean, or a conventional pedal/controller depending on what feels least tiring. Test with a simple Unity kart before connecting to an existing game. The reference Unity body-tracking sample and Kinect Joy Ride give you the software and interaction precedents. citeturn326238search2turn445381search19

**Prototype C: party framework.** Build player enrollment, colored player IDs, a calibration pose, personal interaction zones and reusable gesture primitives—jump, squat, punch, kick, reach, lean, turn, clap, hands-over-head and pose-match. Once this layer exists, bowling, skiing, boxing, dance, reaction games and fitness exercises become game logic rather than new computer-vision projects.

**Prototype D: productivity layer.** Run tracking as a separate local service that emits semantic events over MQTT/WebSocket: `room_occupied`, `desk_posture_warning`, `person_enter_zone`, `exercise_rep`, `point_at_zone`, `raise_hand`. Connect that to Home Assistant rather than letting automation code directly consume raw depth frames. That architecture mirrors contemporary gesture-to-MQTT projects and dramatically reduces coupling. citeturn326238search7turn501679search9

**Prototype E: PS5 experiment.** Keep your PC-native implementation unchanged and add an input-adapter module. Try official Remote Play first with a real DualSense to establish baseline latency. Then experiment with synthetic controller input or, for research use, chiaki-ng. Measure the full interaction loop with high-frame-rate video. Do not make PS5 integration a foundational requirement until you prove that the added latency and unsupported middleware are acceptable. citeturn261907search3turn672751search0

**Prototype F: room-scale interaction.** Add projector calibration and use depth to identify walls/floor/furniture. A good first experience is a floor target that physically reacts when a foot intersects its 3D position, followed by wall-touch, particle silhouettes and player-shadow effects. RoomAliveToolkit and KinectProjectorToolkit are directly relevant references. citeturn475468search2turn475468search9

The biggest missed opportunity in most Kinect projects is treating the camera only as a “skeleton joystick.” A modern depth camera gives you **people + room geometry + proximity + occupancy + body pose + point cloud + surface interaction** simultaneously. The most interesting system for your living room is therefore not merely a Kinect replacement: it is a room-level spatial-computing layer that can switch between gaming, exercise, automation, ergonomics, accessibility and immersive visualization while using the same calibrated coordinate system.

The strongest near-term configuration is therefore **Femto Bolt + PC + Unity + local automation**, not Kinect-to-PS5. Use the PS5 only as an optional downstream target through Remote Play experimentation. If racing and gaming become the main objective, running the game itself on the PC will give you markedly more control over latency, multiple players and custom interactions. If productivity and ambient computing become equally important, retain the same camera stack but expose semantic room events through MQTT/Home Assistant. If four or more people regularly interact, budget from the beginning for a second camera because occlusion—not nominal FOV or maximum skeleton count—will become the dominant technical limitation. citeturn897579search2turn501679search8turn261907search3
