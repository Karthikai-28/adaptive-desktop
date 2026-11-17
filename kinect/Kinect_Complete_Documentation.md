# Kinect: complete research, Ubuntu implementation, and full source code

**Prepared for:** Karthi  
**Compilation date:** November 17, 2026  
**Current hardware and platform:** Kinect v1 / Xbox 360 with Ubuntu PC

## Contents

- [A. Complete earlier research, preserved in full](#complete-research)
  - [Original living-room, productivity, gaming, and PS5 research](#part-i)
  - [Kinect v1 PC games and reuse research](#part-ii)
  - [Fixed Kinect v1 scanning and geometry research](#part-iii)
  - [Original research-launch response](#appendix-a)
  - [Original user requests](#appendix-b)
  - [First report's source index](#appendix-c)
- [B. Delivered Ubuntu codebase overview](#ubuntu-overview)
- [C. Installation, connection, scanning, measurement, and export](#ubuntu-guide)
- [D. Validation results and untested hardware-dependent paths](#ubuntu-validation)
- [E. Implementation references](#ubuntu-references)
- [F. Every source, configuration, installer, and test file](#ubuntu-source)

## Preservation and implementation notes

The earlier research is reproduced in full, not summarized. Its original
wording, tables, code blocks, recommendations, caveats, and links remain in the
archive. Only the first report's chat-specific citation/carousel presentation
is translated into portable Markdown. The original raw-markup copy and all
split reports are also included in the ZIP under `docs/research/`.

The historical reports are not a fresh verification of every old product,
price, availability, or compatibility claim. In particular, the first report
predates the narrowed Kinect v1/PC-only scope. The Ubuntu implementation below
is a separate delivery and clearly identifies its actual capabilities.

**Validation boundary:** 38 automated tests passed and one Open3D-dependent
test was skipped in the authoring environment. The dependency-light synthetic
workflow and file exports were exercised. **No physical Kinect was available;
the Ubuntu installer, actual USB acquisition, graphical preview, real-subject
registration, and Open3D TSDF reconstruction were not tested here.** The
reference installation targets Ubuntu 22.04/24.04 x86-64 and Python 3.10-3.12.

The code implements fixed-camera capture, visible-surface geometry, known-pose
or automatic multi-view workflows, measurements, and geometry export. It does
not infer that hidden surfaces were measured, promise precision metrology,
or automatically make every scan watertight. It does not port the earlier
Windows games to Ubuntu.

---

<a id="complete-research"></a>
# A. Complete earlier research

# Complete Kinect research archive

**Compilation date:** November 17, 2026  
**Contents:** all three previous research reports, their tables, code blocks, recommendations, caveats, links, the original research-launch response, and the user requests.

## Reading this archive

The reports below preserve the earlier wording rather than replacing it with a summary. The first report's chat-only citation and carousel markup is converted to ordinary Markdown links and images in this reading copy; its original markup is retained in the separate `research/01_Living_Room_Productivity_Gaming_PS5_Verbatim.md` file. Reports two and three retain their original Markdown. Original citation URLs and tracking parameters are preserved. Referenced web images remain external images, not bundled image files.

This is a historical compilation, not a new independent validation of every earlier claim. The first report discussed other sensors and consoles before the scope was narrowed to the Kinect v1 you own. Its ratings, prices, availability statements and recommendations should not be treated as specifications for the new Ubuntu codebase. The new implementation guide is separate, and explicitly states what the delivered software does and what was actually tested.

**Mounting clarification:** the original request says “six to seven feet on top of the TV”; the first report interpreted this as height above the floor. That interpretation is not established by the request. Use measured camera height, pitch and subject distance for your installation.

## Contents

- [Part I — Original living-room/productivity/gaming/PS5 report](#part-i)
- [Part II — Kinect v1 PC games and reusable projects](#part-ii)
- [Part III — Fixed Kinect v1 scanning research](#part-iii)
- [Appendix A — Original research-launch response](#appendix-a)
- [Appendix B — Original user requests](#appendix-b)
- [Appendix C — First-report citation index](#appendix-c)

---

<a id="part-i"></a>
# Part I — Original living-room/productivity/gaming/PS5 report

[![Advancements in Methods and Camera-Based Sensors for the Quantification of Respiration | MDPI](https://www.mdpi.com/sensors/sensors-20-07252/article_deploy/html/images/sensors-20-07252-g0A1-550.jpg)](https://www.mdpi.com/1424-8220/20/24/7252)

[![Femto Bolt_高性能TOF相机-奥比中光官网](https://www.orbbec.com.cn/tempFile/sdk/xn.png)](https://www.orbbec.com.cn/index/Product/info.html?cate=38&id=57)

[![Revvvvamped support for Depth Cameras](https://vvvv.org/blog/2020/revvvvamped-support-for-depth-cameras/Kameras-without_r.png)](https://vvvv.org/blog/2020/revvvvamped-support-for-depth-cameras/)

[![Intel Realsense Depth Camera D457 D455 D455f Realsense Depth Camera D457 3D Camera Module Robotics 3D Scanning Drones Realsense Camera - Sensor Camera and Realsense Sensor Camera](https://image.made-in-china.com/368f3j00AGCagyhkfFrB/Intel-Realsense-Depth-Camera-D457-D455-D455f-Realsense-Depth-Camera-D457-3D-Camera-Module-Robotics-3D-Scanning-Drones-Realsense-Camera.webp)](https://m.made-in-china.com/product/Intel-Realsense-Depth-Camera-D457-D455-D455f-Realsense-Depth-Camera-D457-3D-Camera-Module-Robotics-3D-Scanning-Drones-Realsense-Camera-2128025772.html)

# Kinect-Like Depth Sensors for a Multi-Person Living Room: Productivity, Gaming, PS5 Integration, and an Engineering Roadmap

As of **November 17, 2026**, the most important conclusion is that the original Kinect idea is still very useful, but the best modern implementation is no longer “buy a Kinect and plug it into a console.” Microsoft has discontinued Kinect v1/v2, Azure Kinect hardware has been discontinued, and the Azure Kinect SDK reached retirement on August 17, 2024; Microsoft’s sensor repository is archived. The most practical successor for a new build is currently **Orbbec Femto Bolt**, because it reproduces Azure Kinect’s Microsoft iToF depth modes and can run applications written against the Azure Kinect API through Orbbec’s K4A wrapper. RealSense D455/D555, Orbbec Gemini 335, Luxonis OAK-D Pro, and stereo cameras such as ZED 2i are viable alternatives, but they require more of your own pose-tracking/software stack. [R1-1](https://learn.microsoft.com/en-us/lifecycle/products/azure-kinect-sdk) [R1-2](https://github.com/microsoft/Azure-Kinect-Sensor-SDK) [R1-3](https://learn.microsoft.com/en-us/answers/questions/532418/legality-of-using-kinect-as-motion-capture-hardwar) [R1-4](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/About%20Femto%20Bolt) [R1-5](https://www.orbbec.com/products/tof-camera/femto-bolt/)

For your specific room—sensor roughly **6–7 ft / 1.83–2.13 m above the floor, above the television, facing into the room, with several people potentially present**—a Kinect-style system is technically practical. The main design constraint is not raw depth quality; it is maintaining unobstructed views of hands, legs, and torsos when people overlap. A single high-mounted front sensor works well for one to three separated users and can often detect four or more, but a second camera from an oblique angle becomes far more valuable once people stand behind one another, cross paths, play close-contact games, sit on sofas, or use furniture. Orbbec explicitly cites filling occlusion zones as a reason to deploy synchronized multiple depth cameras. [R1-6](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Synchronize%20Multiple%20Femto%20Bolt%20Devices) [R1-7](https://pmc.ncbi.nlm.nih.gov/articles/PMC9002889/)

## What the hardware can actually do in your room

The sensor generations differ much more than their similar appearance suggests. Kinect v1 used structured infrared light and offered roughly a 57° × 43° depth field of view with 20-joint skeletal models; Kinect v2 moved to time-of-flight sensing, widened depth FOV to roughly 70° × 60°, increased the skeleton to 25 joints, and could output whole skeletons for up to six people. Azure Kinect/Femto Bolt moves to a 1-MP time-of-flight depth imager, provides 32-joint Microsoft body tracking, and offers both a 75° × 65° NFOV and an unusually broad 120° × 120° WFOV. [R1-8](https://pmc.ncbi.nlm.nih.gov/articles/PMC5336086/) [R1-9](https://learn.microsoft.com/en-us/previous-versions/windows/kinect/dn772770%28v%3Dieb.10%29) [R1-10](https://www.microsoft.com/en-us/download/details.aspx?id=104015) [R1-11](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Femto%20Bolt%20Hardware%20Specifications)

| Sensor | Technology | Depth FOV | Useful depth range | Depth rate | Skeleton / pose situation | Status in 2026 |
|---|---|---:|---:|---:|---|---|
| Kinect v1 / Xbox 360 | Structured light | ~57° × 43° | ~1.2–3.5 m sweet spot | ~30 FPS | 20 joints; up to two fully tracked active players in the classic gaming model | Discontinued; cheap used hardware [R1-12](https://pmc.ncbi.nlm.nih.gov/articles/PMC4782741/) [R1-13](https://learn.microsoft.com/en-us/answers/questions/1210718/how-to-record-seated-mode-in-kinect-v1) |
| Kinect v2 / Xbox One | ToF | ~70° × 60° | ~0.5–4.5 m | 30 FPS | 25 joints; up to six full bodies | Discontinued, but still useful on PC with legacy SDK/libfreenect2 [R1-14](https://download.microsoft.com/download/6/7/6/676611b4-1982-47a4-a42e-4cf84e1095a8/kinecthig.2.0.pdf) [R1-15](https://github.com/OpenKinect/libfreenect2) |
| Azure Kinect DK | iToF | 75° × 65° NFOV; 120° × 120° WFOV | 0.25–5.46 m depending mode | Up to 30 FPS | 32 joints, multiple people; practical body count constrained by compute | Hardware and SDK EOL; used only [R1-16](https://pmc.ncbi.nlm.nih.gov/articles/PMC9879399/) [R1-1](https://learn.microsoft.com/en-us/lifecycle/products/azure-kinect-sdk) [R1-17](https://github.com/microsoft/Azure-Kinect-Sensor-SDK/blob/develop/kinect-qa.md?plain=1) |
| **Orbbec Femto Bolt** | Microsoft-derived iToF | 75° × 65° / 120° × 120° | 0.25–5.46 m | Up to 30 FPS | Orbbec skeleton SDK or Microsoft Azure body tracker through K4A wrapper | **Best Kinect-like migration path** [R1-18](https://www.orbbec.com/products/tof-camera/femto-bolt/) [R1-4](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/About%20Femto%20Bolt) |
| Orbbec Gemini 335 | Active/passive stereo | 90° × 65° | 0.10–20 m+, optimum ~0.26–3 m | 1280×800 @ 30 FPS | Requires Orbbec/custom pose pipeline | Current, inexpensive, strong general CV choice [R1-19](https://www.orbbec.com/products/stereo-vision-camera/gemini-335/) [R1-20](https://store.orbbec.com/products/gemini-335) |
| RealSense D455 | Stereo | ~87° × 58° | ideal ~0.6–6 m | Up to 90 FPS depth | No Kinect-equivalent integrated Microsoft skeleton API; use external pose stack/OpenNI/NiTE/custom | Current [R1-21](https://www.realsenseai.com/products/450-series/) [R1-22](https://dev.realsenseai.com/sdk-2-0-code-samples-wrappers-and-languages/openni/) |
| RealSense D555 | Stereo, PoE | 87° × 58° | ideal ~0.6–6 m | Up to 90 FPS | Same general software model as RealSense SDK 2.0 | Current, good remote-placement option [R1-23](https://www.realsenseai.com/products/d555-poe/) [R1-24](https://realsenseai.com/wp-content/uploads/2025/08/D555-Datasheet-v1.1.pdf) |
| Luxonis OAK-D Pro | Active stereo + onboard AI | ~80° × 55° stereo cameras | ideal ~0.7–12 m | Sensor-dependent | Run neural pose models on/through DepthAI | Current; attractive for embedded AI [R1-25](https://shop.luxonis.com/products/oak-d-pro?Central+RGB+Camera=OV9782) [R1-26](https://checkout.luxonis.com/products/oak-d-pro) |

For your mounting height, **Femto Bolt NFOV unbinned at 640×576/30 FPS is the mode I would start with**. Its documented range is 0.5–3.86 m and FOV is 75° × 65°; NFOV binned extends the specified range to 5.46 m but reduces depth resolution to 320×288. WFOV gives a spectacular 120° × 120°, but at 30 FPS its binned operating range is only about 2.88 m. [R1-11](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Femto%20Bolt%20Hardware%20Specifications) [R1-27](https://www.orbbec.com/wp-content/uploads/2023/08/ORBBEC_Datasheet_Femto-Bolt-2.pdf)

At a 3 m subject distance, a 75° horizontal FOV spans approximately **4.6 m of room width**; at 4 m it spans about **6.1 m**. Those are geometric calculations from the documented 75° FOV, so an NFOV sensor above a TV can already cover a normal living-room play zone without needing the 120° mode. The wide mode becomes useful if people stand very close to the TV or if the room is unusually wide. [R1-11](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Femto%20Bolt%20Hardware%20Specifications)

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

With a 65° vertical NFOV, mounting around 2 m and pitching the optical axis downward around **10–15°** is a sensible first calibration point: it provides enough downward coverage to retain feet at normal play distances without turning the camera into an overhead/top-down view. That pitch is an engineering recommendation rather than a Microsoft-prescribed value; Microsoft did not publish one universal “optimal height,” and its own guidance notes that lighting, obstruction, body height and scene conditions all affect tracking. Community reports also show that tilted-camera coordinates must be transformed into your room/floor frame if you want intuitive gesture directions. [R1-28](https://github.com/microsoft/Azure-Kinect-Sensor-SDK/issues/1168) [R1-29](https://learn.microsoft.com/en-us/answers/questions/1336175/what-is-the-highest-accuracy-range-of-the-kinect-w) [R1-30](https://learn.microsoft.com/en-gb/answers/questions/231523/azure-kinect-point-cloud)

I would **not mount the sensor on the ceiling pointing steeply downward** if your primary goal is skeletal gaming. Body trackers work best when the camera sees recognizable frontal or three-quarter human silhouettes. Research on Kinect placement repeatedly finds that sensor position and self-occlusion strongly influence joint accuracy, and an Azure Kinect posture study found its most stable results in that experiment at roughly 1.6–2.2 m camera-to-person distance. [R1-31](https://pmc.ncbi.nlm.nih.gov/articles/PMC4327103/) [R1-32](https://pmc.ncbi.nlm.nih.gov/articles/PMC10551660/)

For one player, one camera is enough. For two players, one Femto Bolt/Kinect v2 is generally comfortable if they remain side-by-side. For three to four active people, widen the spacing and avoid one person standing directly behind another. For four-plus users doing aggressive movement, dancing, or party games, **two cameras at roughly 30–60° relative viewpoints** are a much more robust architecture than trying to solve occlusion algorithmically. Femto Bolt supports hardware synchronization through its sync port and multiple devices on one host if USB/compute resources permit. [R1-6](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Synchronize%20Multiple%20Femto%20Bolt%20Devices) [R1-33](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Record%20Multi-Device%20Synchronized%20Data%20with%20Femto%20Bolt%20Recorder)

Lighting is usually less problematic for ToF than ordinary RGB vision indoors, but direct sunlight and strong IR contamination remain enemies of infrared depth systems. Kinect v2 measurements have been shown to degrade under direct sunlight, and Azure Kinect accuracy studies intentionally block direct sun when making precision measurements. Stereo alternatives such as RealSense can work over longer distances but themselves depend on texture/IR projection and lighting conditions. [R1-34](https://www.mdpi.com/1424-8220/15/11/27569.) [R1-7](https://pmc.ncbi.nlm.nih.gov/articles/PMC9002889/) [R1-35](https://www.realsenseai.com/wp-content/uploads/2024/10/Intel-RealSense-D400-Series-Datasheet-October-2024.pdf)

Latency is also important for games. Most Kinect-class depth pipelines run at 30 FPS, meaning a new depth frame arrives every 33.3 ms before pose inference, filtering and game logic are considered. Real Azure Kinect systems have sustained near-30-FPS body tracking on GPUs such as an RTX 2060, although Microsoft community reports also document configurations with noticeable tracker delay. For a responsive game, you should treat latency as an end-to-end engineering metric rather than “camera FPS”: timestamp capture, skeleton output, gesture recognition, virtual-controller output and display response separately. [R1-36](https://github.com/microsoft/Azure-Kinect-Sensor-SDK/issues/1043) [R1-37](https://github.com/microsoft/Azure-Kinect-Sensor-SDK/issues/816)

## Games and entertainment: what you can play versus what you must build

There are two completely different ecosystems here: **legacy Kinect games**, which are finished commercial experiences designed for Xbox 360/Xbox One hardware, and **new PC experiences**, where a depth camera becomes an input device for software you create or adapt.

The original Kinect game library is still the best proof of what this interaction model can accomplish. Xbox’s Kinect launch lineup included Kinect Adventures, Kinect Sports, Kinectimals, Kinect Joy Ride and many others; Kinect Joy Ride was explicitly a controller-free kart racer. Dance Central was a full-body tracked dance game. Kinect Sports Rivals on Xbox One included wake racing, climbing, tennis, bowling, soccer and target shooting and supported two-to-four-player local multiplayer. [R1-38](https://news.xbox.com/en-us/2010/10/19/announcing-the-kinect-launch-portfolio/) [R1-39](https://news.xbox.com/en-us/2010/11/05/demo-kinect-joyride/?ver=3.7.1) [R1-40](https://news.xbox.com/en-us/2011/03/15/demo-dance-central/?ver=3.7.1) [R1-41](https://www.xbox.com/en-in/games/store/kinect-sports-rivals/brhsml8030zn)

| Experience | Interaction | Ready to play? | Best way to reproduce today |
|---|---|---|---|
| **Kinect Joy Ride** | Hold imaginary steering wheel, steer with arms/body | Yes, but on Xbox 360 + Kinect | Legacy Xbox 360 hardware; or build similar PC control mapping [R1-39](https://news.xbox.com/en-us/2010/11/05/demo-kinect-joyride/?ver=3.7.1) |
| **Forza Motorsport 4 Kinect features** | Kinect-enhanced automotive interaction alongside traditional controls | Legacy Xbox 360 | Legacy hardware only for authentic implementation [R1-42](https://news.xbox.com/en-us/2011/10/03/demo-forza-motorsport-4/?ver=3.7.1) |
| **Kinect Sports / Sports Rivals** | Bowling, tennis, soccer, climbing, wake racing, shooting | Yes on original supported consoles | Xbox One + Kinect v2 for Rivals [R1-41](https://www.xbox.com/en-in/games/store/kinect-sports-rivals/brhsml8030zn) |
| **Dance Central / Spotlight** | Full-body choreography recognition | Yes on supported Xbox hardware | Kinect v1/v2 legacy Xbox setup [R1-43](https://news.xbox.com/en-us/2014/06/10/events-dance-central-e3/) [R1-40](https://news.xbox.com/en-us/2011/03/15/demo-dance-central/?ver=3.7.1) |
| **Kinect Adventures** | Jumping, leaning, dodging, whole-body interaction | Legacy Xbox 360 | Xbox 360 Kinect bundle/software [R1-44](https://news.xbox.com/en-us/2010/07/20/announcing-kinect-pricing-xbox-360-4-gb-console-and-holiday-bundle/) |
| **Kinectimals** | Reach, gesture and interact with virtual animals | Legacy Xbox 360 | Original console/sensor [R1-45](https://nxeassets.xbox.com/shaxam/0201/c3/e1/c3e1b51a-8c8e-4efb-ad5d-ad3f6e9fe5eb.PDF?v=1) |
| **Tiger Woods PGA Tour 13** | Golf swing/body motion | Legacy Kinect integration | Xbox 360 setup [R1-46](https://news.xbox.com/en-us/2012/03/05/a-preview-of-xbox-360-kinect-arcade-and-windows-phone-games/) |
| **Fable: The Journey** | Arm/gesture actions | Legacy Kinect | Xbox 360 setup [R1-46](https://news.xbox.com/en-us/2012/03/05/a-preview-of-xbox-360-kinect-arcade-and-windows-phone-games/) |
| **RoomAlive-style games** | Touch walls, shoot, stomp, dodge, steer projected objects | Research prototype / custom | PC + one or more depth cameras + projector(s) [R1-47](https://www.microsoft.com/en-us/research/project/roomalive/) [R1-48](https://github.com/microsoft/RoomAliveToolkit) |
| **Point-cloud avatar / volumetric mirror** | Real-time 3D reconstruction of players | Custom | Unity/Unreal + RGB-D point cloud pipeline [R1-49](https://github.com/rfilkov/AzureKinectUnityFree) [R1-50](https://github.com/widVE/KinectCloud) |
| **Virtual wall/table touch** | Hands become touch points on ordinary surfaces | Custom | Calibrated depth camera + surface plane detection [R1-51](https://www.microsoft.com/en-us/research/video/using-depth-camera-touch-sensor-2/) |

For your **car-game idea**, the easiest convincing prototype is not to begin with skeleton-to-PS5 integration. Begin on a PC: map shoulder midpoint to steering center, calculate the vector between hands as an imaginary steering wheel, derive steering angle from that vector, use forward hand displacement or hand state for throttle/brake, and emit an XInput joystick axis. A second mode can use hip lateral displacement as steering so children or casual players do not need to hold their arms up continuously. Kinect Joy Ride demonstrates that the interaction concept is viable; your modern implementation can use significantly richer skeleton data. [R1-39](https://news.xbox.com/en-us/2010/11/05/demo-kinect-joyride/?ver=3.7.1) [R1-10](https://www.microsoft.com/en-us/download/details.aspx?id=104015)

Other living-room games that map unusually well to one overhead-TV sensor include boxing, skiing, snowboard lean, goalkeeper, penalty kicks, cricket/baseball batting, tennis, archery, rhythm/dance, “floor is lava,” obstacle dodging, balance challenges, Simon Says, charades recognition, freeze dance, cooperative pose matching, virtual sword fighting, fitness races, and asymmetric multiplayer where one person’s arms steer while another person’s stance controls acceleration. These are custom applications, but they use exactly the body/joint information exposed by Kinect-class trackers rather than requiring exotic point-cloud algorithms. Microsoft’s Body Tracking SDK returns independently identified multi-person skeletons and 32 joints per person for Azure Kinect-compatible systems. [R1-10](https://www.microsoft.com/en-us/download/details.aspx?id=104015) [R1-5](https://www.orbbec.com/products/tof-camera/femto-bolt/)

The more unusual experiences come from ignoring the skeleton entirely and using the **point cloud**. You can make players appear as particles, melt their silhouettes into the walls, create trails and spatial echoes, erase portions of the room, make virtual objects collide with people, reveal invisible objects as people walk around them, create volumetric freeze frames, or render one person from another viewpoint. Microsoft’s RoomAlive prototype demonstrated room-scale projected games in which users could touch, shoot, stomp, dodge and steer projected content, while MirageTable and HoloDesk demonstrated freehand interaction between depth-captured physical objects and virtual geometry. [R1-47](https://www.microsoft.com/en-us/research/project/roomalive/) [R1-52](https://www.microsoft.com/en-us/research/publication/miragetable-freehand-interaction-projected-augmented-reality-tabletop/) [R1-53](https://www.microsoft.com/en-us/research/project/holodesk-direct-3d-interactions-with-a-situated-see-through-display/)

RoomAlive is especially relevant to your ceiling/high-TV idea. Microsoft released an open-source toolkit that calibrates multiple Kinect/projector pairs and streams depth data into Unity; their large demonstration used six Kinect cameras and six projectors. You do not need six units for a living room—a single projector plus one depth camera can make an interactive wall/floor—but the research establishes that a complete room can be treated as a playable surface. [R1-54](https://www.microsoft.com/en-us/research/project/roomalive-toolkit/) [R1-48](https://github.com/microsoft/RoomAliveToolkit)

## Day-to-day productivity: what is genuinely useful

The strongest productivity use is **ambient interaction**, where the system does something useful because it knows where people are and what they are doing without requiring phones, remotes, keyboards or wearable trackers.

A 2026 IEEE home/building interaction project is particularly relevant: it used depth-camera pointing gestures to control Home Assistant devices, reporting **96% average gesture accuracy and 26.67 ms average recognition latency** in its experiment, while emphasizing that depth-only imagery offers more privacy than ordinary RGB video. That is a credible modern implementation of “point at the lamp / point at the fan / gesture to change a device” rather than an old Kinect novelty. [R1-55](https://ieeexplore.ieee.org/abstract/document/11701707/)

Ergonomics is another genuinely useful category. Kinect-based research has demonstrated automatic extraction of joint geometry for RULA-style posture assessment, while later Azure Kinect work validated a system for screening shoulder imbalance, pelvic tilt, forward head, scoliosis and related static posture characteristics against optical motion capture. These systems are not medical diagnostic replacements, but the evidence is substantially stronger than for novelty gesture controls. [R1-31](https://pmc.ncbi.nlm.nih.gov/articles/PMC4327103/) [R1-56](https://pmc.ncbi.nlm.nih.gov/articles/PMC10551660/)

For a home office, that translates into applications such as detecting prolonged slouching, desk-to-standing transitions, neck/shoulder posture, time spent sitting versus standing, repeated reaching patterns and exercise breaks. You should treat these as trend/behavioral signals rather than millimeter-accurate biomechanics because body tracking degrades under self-occlusion and unfavorable camera angles. [R1-31](https://pmc.ncbi.nlm.nih.gov/articles/PMC4327103/) [R1-57](https://pmc.ncbi.nlm.nih.gov/articles/PMC4076760/)

Exercise and rehabilitation have some of the deepest evidence. Kinect has been studied in home stroke exercise, chronic-stroke balance telerehabilitation, geriatric exergaming and long-duration home shoulder rehabilitation. A 2025 randomized study of 60 pre-frail older adults compared Kinect aerobic dance against video-based home exercise over eight weeks. These studies collectively support the idea that body-tracked exercise can improve adherence, give real-time feedback and make repetitive movement programs more engaging, although effect sizes and clinical populations vary. [R1-58](https://pubmed.ncbi.nlm.nih.gov/27563384/) [R1-59](https://pubmed.ncbi.nlm.nih.gov/40567995/) [R1-60](https://pubmed.ncbi.nlm.nih.gov/33902646/) [R1-61](https://pubmed.ncbi.nlm.nih.gov/28330455/) [R1-62](https://pmc.ncbi.nlm.nih.gov/articles/PMC7537442/)

Accessibility is another underused area. A depth camera can recognize large gestures for people who have difficulty manipulating small controls, detect pointing without speech, or combine movement with PlayStation’s own assist-controller functionality. Sony allows supported PS5 controllers to be paired as an assist controller so two controllers act as one, although this does **not** make a Kinect an officially supported PS5 controller. [R1-55](https://ieeexplore.ieee.org/abstract/document/11701707/) [R1-63](https://www.playstation.com/en-in/support/hardware/second-controller-assistance/)

Telepresence is more technically demanding but increasingly interesting. Microsoft’s Room2Room captured a person in 3D and projected a life-size representation into a remote space; a 2026 multi-view telepresence study fused three cameras into a point-cloud view for XR robot teleoperation and found that its mixed 3D/high-resolution representation performed better overall than the compared visualization modes in its 31-person study. [R1-64](https://www.microsoft.com/en-us/research/project/room2room-life-size-telepresence-projected-augmented-reality-environment/) [R1-65](https://arxiv.org/abs/2604.03730)

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

The general lesson from fifteen years of Kinect experimentation is that **gesture works best for coarse spatial actions, not high-frequency precision input**. “Point at this,” “raise both hands,” “step into this zone,” “start my workout,” “pause,” “next track,” or “recognize this exercise repetition” are natural. Replacing a mouse with hand waving is tiring and less precise; depth-camera touch research itself notes that camera-based touch is less precise than direct capacitive sensing. [R1-51](https://www.microsoft.com/en-us/research/video/using-depth-camera-touch-sensor-2/)

## PS5: what works, what does not, and the realistic architecture

A Kinect, Azure Kinect, Femto Bolt, RealSense or similar USB depth camera **does not have native PS5 game-input support**. Sony’s PS5 USB documentation enumerates supported controller classes, PS VR/VR2 hardware, the HD Camera and officially licensed specialty peripherals; Kinect-style generic RGB-D cameras are not part of the supported interface. Sony’s own PS5 HD Camera is primarily for 1080p capture/broadcast features, not Kinect-style skeletal gameplay. [R1-66](https://www.playstation.com/en-ca/support/hardware/ps5-hd-camera-support/) [R1-67](https://www.playstation.com/en-ae/support/hardware/ps5-usb-ports-guide/) [R1-68](https://www.playstation.com/en-in/accessories/hd-camera/)

So this architecture will **not** work:

```text
Kinect / Femto Bolt ──USB──> PS5 ──> arbitrary motion-controlled PS5 game
                         ✗
```

The console has no Kinect driver, no Azure/Orbbec SDK, no user-installable middleware layer and no standard mechanism by which an arbitrary USB depth sensor can expose skeletons to a PS5 title. Sony also states that PS5 games require supported PS5 controllers, while compatibility for third-party peripherals is device/title dependent. [R1-67](https://www.playstation.com/en-ae/support/hardware/ps5-usb-ports-guide/) [R1-69](https://www.playstation.com/en-gb/support/games/ps5-backward-compatibility-games/)

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

The **PC-native path is by far the better engineering choice**. You control the entire latency pipeline, can support multiple players, can run Unity or Unreal directly, and can map the sensor to XInput/keyboard/mouse or directly into game logic. Microsoft still publishes Azure Kinect samples including Unity body-tracking examples, while community projects provide Unity point-cloud rendering and Kinect/Azure wrappers. [R1-70](https://github.com/microsoft/Azure-Kinect-Samples/blob/master/body-tracking-samples/sample_unity_bodytracking/README.md) [R1-71](https://github.com/microsoft/azure-kinect-samples) [R1-49](https://github.com/rfilkov/AzureKinectUnityFree)

For PS5, the legitimate supported bridge is **PS Remote Play**: Sony supports streaming a PS5 to Windows/macOS and expects a DualSense, DualSense Edge or DualShock 4 as the PC-side controller. Sony recommends at least 15 Mbps for a better Remote Play experience. [R1-72](https://www.playstation.com/en-us/remote-play/) [R1-73](https://www.playstation.com/en-ph/support/games/playstation-remote-play-on-pc-and-mac/)

A depth-camera prototype can therefore recognize body movements on the PC and translate them into controller-like events, but getting those synthetic events accepted by the official Remote Play client is the weak point. Older Windows virtual-gamepad systems such as ViGEm could emulate Xbox 360 or DualShock 4 devices and were explicitly used for unsupported input devices and Remote Play, but **ViGEmBus itself is retired and its repository has been archived since 2023**. That makes it unsuitable as the foundation for a long-lived product. [R1-74](https://github.com/nefarius/vigembus) [R1-75](https://github.com/nefarius/ViGEmBus/releases)

An alternative experimental path is the open-source **chiaki-ng** Remote Play client. As of November 2026 it remains actively maintained, supports PS4/PS5 Remote Play across Windows, Linux and other platforms, and its current code includes controller-input transmission back to the console. It is explicitly not endorsed or certified by Sony, so firmware/protocol changes can break it and you should treat it as a research/hobbyist integration rather than a supported console interface. [R1-76](https://github.com/chiaki-ng/chiaki-ng?pubDate=20260509) [R1-77](https://github.com/chiaki-ng/chiaki-ng/blob/main/gui/io.github.streetpea.Chiaki4deck.appdata.xml) [R1-78](https://github.com/chiaki-ng/chiaki-ng/blob/main/CONTRIBUTOR_GUIDE.md)

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

At 30-FPS depth capture alone, the sampling interval is 33.3 ms; the Remote Play route then adds networking, encode/decode and display delay on top. Sony does not publish a universal end-to-end Remote Play latency because it depends on network and client hardware, so any fixed “50 ms” or “100 ms” claim would be misleading. For bowling, fitness, dance, party or turn-based motion experiences it can be tolerable; for precision racing, fighting games or competitive shooters, the PC-native path is considerably more appropriate. [R1-79](https://microsoft.github.io/Azure-Kinect-Sensor-SDK/master/namespace_microsoft_1_1_azure_1_1_kinect_1_1_sensor_abcc6077f50ba0a9f28733212991e7aa0.html) [R1-72](https://www.playstation.com/en-us/remote-play/)

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

For Kinect v1, **libfreenect** remains the canonical open-source driver stack and exposes RGB, depth, motor, accelerometer, LED and audio functions across Linux, macOS and Windows. Kinect v2 has **libfreenect2**, which supports RGB, IR, depth and RGB-depth registration. These are valuable if you want cheap hardware experiments without depending on Microsoft’s old Windows SDK. [R1-80](https://github.com/OpenKinect/libfreenect) [R1-15](https://github.com/OpenKinect/libfreenect2)

For Azure Kinect/Femto Bolt, Microsoft’s **Azure-Kinect-Samples** repository remains an excellent reference even though the underlying Microsoft stack is archived. It contains Sensor SDK and Body Tracking SDK examples, including a Unity skeleton sample. Orbbec’s K4A wrapper is specifically designed to preserve compatibility with Azure Kinect applications on Femto Bolt. [R1-71](https://github.com/microsoft/azure-kinect-samples) [R1-70](https://github.com/microsoft/Azure-Kinect-Samples/blob/master/body-tracking-samples/sample_unity_bodytracking/README.md) [R1-81](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Orbbec%20SDK%20and%20Orbbec%20SDK%20K4A%20Wrapper%20%28Femto%20Bolt%29)

For visual experimentation, **AzureKinectUnityFree** includes an environment point-cloud VFX demo, while **KinectCloud** can capture colored Azure Kinect point clouds and stream them to Unity. These give you a quick route to “digital ghost,” particles, volumetric avatar and room-deformation prototypes without first writing your own depth-to-XYZ conversion. [R1-49](https://github.com/rfilkov/AzureKinectUnityFree) [R1-50](https://github.com/widVE/KinectCloud)

For projection, **Microsoft RoomAliveToolkit** is still one of the most instructive codebases because it covers projector-camera calibration, multiple Kinects and Unity integration. The independent KinectProjectorToolkit demonstrates body projection, background manipulation and even a simple game where falling polygons interact with a person on a wall. [R1-48](https://github.com/microsoft/RoomAliveToolkit) [R1-82](https://github.com/genekogan/kinectprojectortoolkit)

For home automation, the modern pattern is to decouple perception from automation using **MQTT/Home Assistant**. One current open-source Home Assistant project recognizes hand gestures from camera frames and publishes them over MQTT so automations can react. It is RGB/MediaPipe-oriented rather than Kinect-specific, but the architecture—perception service → semantic gesture → MQTT event → automation—is exactly how I would structure your room controller. [R1-83](https://github.com/benja-opazo/home-assistant-hand-recognition)

A useful sign that the platform still attracts experimentation is that Kinect/Azure enthusiasts continue building dance and alternative tracking systems even after Microsoft stopped support; however, recent community projects that replace proprietary depth or body-tracking components should be treated as experimental until independently validated. [R1-84](https://www.reddit.com/r/kinect/comments/1wrosag/just_discovered_secret_features_on_the_azure/)

## Costs, privacy, safety, and the things most people overlook

Current pricing strongly favors starting with used Kinect hardware for proof-of-concept and buying a current camera only once you understand your interaction requirements. In November 2026, Orbbec’s official store lists Femto Bolt at **$418 but currently out of stock**; Gemini 335 is **$264**; RealSense lists D455 and D555 around **$499**; OAK-D Pro is around **$429**. Current U.S. used listings show Kinect v2 bundles around tens to roughly a hundred dollars, while Azure Kinect pricing is highly volatile because the product is discontinued—current listings commonly range into several hundred dollars despite some auctions having sold much lower. [R1-85](https://store.orbbec.com/products/femto-bolt) [R1-20](https://store.orbbec.com/products/gemini-335) [R1-86](https://www.realsenseai.com/products/450-series/) [R1-87](https://www.realsenseai.com/compare-all-cameras/) [R1-25](https://shop.luxonis.com/products/oak-d-pro?Central+RGB+Camera=OV9782) [R1-88](https://www.ebay.com/sch/i.html?_nkw=microsoft+kinect+sensor+v2&_sop=12) [R1-89](https://www.ebay.com/sch/i.html?_nkw=azure+kinect&_sop=12)

| Budget | Hardware | What I would build |
|---|---|---|
| **$30–100 experiment** | Used Kinect v1/v2 + required PC adapter | Skeleton/gesture prototype, racing control, exercise counter |
| **$250–350 modern stereo** | Gemini 335 | Depth/point cloud + your own pose model; excellent CV experimentation |
| **$400–550 Kinect-successor** | Femto Bolt when available | Best route to Azure-Kinect-style skeleton tracking and Unity applications |
| **$500–800 embedded/AI** | OAK-D Pro or RealSense + capable GPU/mini-PC | Custom AI, high-rate depth, robotics-style pipelines |
| **$900–1,500+ serious room system** | Two depth cameras + PC + mounts | Reduced occlusion, 3–4+ player interaction |
| **$1,500+ immersive room** | Two-plus cameras + projector(s) | Interactive wall/floor, RoomAlive-like experiences |

The camera price is not the entire system cost. Body tracking is compute-heavy: Orbbec’s own Femto Bolt recommendations assume NFOV unbinned at 30 FPS while tracking five people, and a serious Unity application benefits from a discrete GPU. Cabling is also nontrivial: Femto Bolt is USB 3.2, and Orbbec warns that passive USB-C runs should generally remain short, recommending active cabling for longer installations. That matters when the camera is mounted permanently above a television and the PC is elsewhere. [R1-90](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Femto%20Bolt%203D%20Camera%20SDK%20System%20Requirements) [R1-11](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Femto%20Bolt%20Hardware%20Specifications)

Privacy deserves more attention than most Kinect hobby projects gave it. Depth-only processing reduces visual identity exposure compared with conventional RGB recording, but a point cloud still reveals room geometry, body dimensions, movement patterns, occupancy and potentially identifiable gait. Volumetric systems can also leak private objects through geometry even if RGB imagery is removed; recent research on privacy-preserving volumetric streaming explicitly treats depth as sensitive data. [R1-55](https://ieeexplore.ieee.org/abstract/document/11701707/) [R1-91](https://arxiv.org/abs/2608.11645)

For a permanent living-room system I would therefore process frames locally, disable RGB unless an application needs it, retain only semantic events such as `person_2 / squat / repetition_14`, avoid continuous video storage, provide a physical sensor power switch or visible hardware indicator, and separate raw-camera services from Home Assistant/network services. Those are architectural recommendations based on the privacy properties of depth and volumetric capture rather than manufacturer requirements. [R1-91](https://arxiv.org/abs/2608.11645)

Physical safety is equally important for games. Your system must know the playable floor polygon and reject actions near TVs, tables, fans, stairs and walls. A depth camera gives you enough room geometry to do something conventional console motion systems rarely did well: maintain a **dynamic safety envelope** and pause the game if a player approaches an obstacle or another player too closely. Room-scale projection research demonstrates that depth systems can build and continuously update spatial models of a room, although your safety implementation would need its own validation. [R1-47](https://www.microsoft.com/en-us/research/project/roomalive/) [R1-48](https://github.com/microsoft/RoomAliveToolkit)

Another overlooked issue is **identity persistence**. Body trackers give each currently observed body an ID, but an ID is not a reliable permanent identity if a person leaves the field of view and returns. For multiplayer profiles you should re-associate players using starting zones, explicit “raise hand to join” enrollment, clothing appearance if RGB is enabled, or other session-level logic rather than trusting tracker IDs forever.

Furniture is a major source of failure. Sofas hide knees and feet, coffee tables create lower-body occlusion, and one human standing behind another can cause inferred rather than observed joint positions. Kinect ergonomics studies report exactly these kinds of problems in realistic scenes, and Microsoft/Orbbec multi-camera guidance treats occlusion as a primary reason for multiple viewpoints. [R1-57](https://pmc.ncbi.nlm.nih.gov/articles/PMC4076760/) [R1-6](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Synchronize%20Multiple%20Femto%20Bolt%20Devices)

## Recommended architecture and implementation roadmap

For your requirements, my first-choice architecture is **one Femto Bolt above the television + Windows PC with an NVIDIA GPU + Unity**, with the mechanical mount deliberately designed so a second Femto Bolt or other depth camera can later be added at a side wall. If Femto Bolt availability remains poor, a used Azure Kinect is acceptable for prototyping but not attractive for a long-lived product because Microsoft hardware and SDK support have ended. A used Kinect v2 is even cheaper and can teach you nearly everything about game design before you spend money on the final sensor. [R1-85](https://store.orbbec.com/products/femto-bolt) [R1-1](https://learn.microsoft.com/en-us/lifecycle/products/azure-kinect-sdk) [R1-2](https://github.com/microsoft/Azure-Kinect-Sensor-SDK)

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

**Prototype A: tracking validation.** Mount the camera around 1.9–2.1 m high, start at about 10–15° downward pitch, use NFOV unbinned/30 FPS, mark floor positions at approximately 1.5, 2, 2.5, 3, 3.5 and 4 m, and record skeleton confidence for one through four people. Test crossing, sitting, crouching, turning sideways, one person walking behind another, children versus adults and lights-on/lights-off conditions. The goal is to produce a room-specific tracking-quality heat map, not merely confirm that a skeleton appears. [R1-11](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Femto%20Bolt%20Hardware%20Specifications) [R1-29](https://learn.microsoft.com/en-us/answers/questions/1336175/what-is-the-highest-accuracy-range-of-the-kinect-w)

**Prototype B: body-controlled racer.** Use Unity. Calculate steering from the angle between hands or shoulder/hip rotation, normalize it to −1…+1, add a dead zone and exponential/spline response, then apply temporal smoothing. Map throttle to one foot forward, hand extension, lean, or a conventional pedal/controller depending on what feels least tiring. Test with a simple Unity kart before connecting to an existing game. The reference Unity body-tracking sample and Kinect Joy Ride give you the software and interaction precedents. [R1-70](https://github.com/microsoft/Azure-Kinect-Samples/blob/master/body-tracking-samples/sample_unity_bodytracking/README.md) [R1-39](https://news.xbox.com/en-us/2010/11/05/demo-kinect-joyride/?ver=3.7.1)

**Prototype C: party framework.** Build player enrollment, colored player IDs, a calibration pose, personal interaction zones and reusable gesture primitives—jump, squat, punch, kick, reach, lean, turn, clap, hands-over-head and pose-match. Once this layer exists, bowling, skiing, boxing, dance, reaction games and fitness exercises become game logic rather than new computer-vision projects.

**Prototype D: productivity layer.** Run tracking as a separate local service that emits semantic events over MQTT/WebSocket: `room_occupied`, `desk_posture_warning`, `person_enter_zone`, `exercise_rep`, `point_at_zone`, `raise_hand`. Connect that to Home Assistant rather than letting automation code directly consume raw depth frames. That architecture mirrors contemporary gesture-to-MQTT projects and dramatically reduces coupling. [R1-83](https://github.com/benja-opazo/home-assistant-hand-recognition) [R1-55](https://ieeexplore.ieee.org/abstract/document/11701707/)

**Prototype E: PS5 experiment.** Keep your PC-native implementation unchanged and add an input-adapter module. Try official Remote Play first with a real DualSense to establish baseline latency. Then experiment with synthetic controller input or, for research use, chiaki-ng. Measure the full interaction loop with high-frame-rate video. Do not make PS5 integration a foundational requirement until you prove that the added latency and unsupported middleware are acceptable. [R1-72](https://www.playstation.com/en-us/remote-play/) [R1-76](https://github.com/chiaki-ng/chiaki-ng?pubDate=20260509)

**Prototype F: room-scale interaction.** Add projector calibration and use depth to identify walls/floor/furniture. A good first experience is a floor target that physically reacts when a foot intersects its 3D position, followed by wall-touch, particle silhouettes and player-shadow effects. RoomAliveToolkit and KinectProjectorToolkit are directly relevant references. [R1-48](https://github.com/microsoft/RoomAliveToolkit) [R1-82](https://github.com/genekogan/kinectprojectortoolkit)

The biggest missed opportunity in most Kinect projects is treating the camera only as a “skeleton joystick.” A modern depth camera gives you **people + room geometry + proximity + occupancy + body pose + point cloud + surface interaction** simultaneously. The most interesting system for your living room is therefore not merely a Kinect replacement: it is a room-level spatial-computing layer that can switch between gaming, exercise, automation, ergonomics, accessibility and immersive visualization while using the same calibrated coordinate system.

The strongest near-term configuration is therefore **Femto Bolt + PC + Unity + local automation**, not Kinect-to-PS5. Use the PS5 only as an optional downstream target through Remote Play experimentation. If racing and gaming become the main objective, running the game itself on the PC will give you markedly more control over latency, multiple players and custom interactions. If productivity and ambient computing become equally important, retain the same camera stack but expose semantic room events through MQTT/Home Assistant. If four or more people regularly interact, budget from the beginning for a second camera because occlusion—not nominal FOV or maximum skeleton count—will become the dominant technical limitation. [R1-6](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Synchronize%20Multiple%20Femto%20Bolt%20Devices) [R1-57](https://pmc.ncbi.nlm.nih.gov/articles/PMC4076760/) [R1-72](https://www.playstation.com/en-us/remote-play/)

---

<a id="part-ii"></a>
# Part II — Kinect v1 PC games and reusable projects

# Kinect v1 on PC: games, reusable projects, and implementation paths

Karthi, **there are useful Kinect v1 PC projects you can reuse without building the tracking or game logic from scratch**. The strongest starting points I found are **RunStickmanRun** for a complete game, **FAAST** for controlling existing PC games, and **Kinect with MS-SDK** for a reusable Unity integration. ([GitHub](https://github.com/gbaelen/RunStickmanRun?utm_source=chatgpt.com))

The important distinction is between **a downloadable game**, **source code that needs rebuilding**, and **middleware that adds motion controls to another game**. Many search results blur these categories.

**Research checked: November 17, 2026.** I inspected project documentation, repository contents, and selected implementation code. I have not compiled these projects or tested them with a physical Kinect, so “executable included” below does not mean “verified working on your PC.”

## 1. The best starting points for your requirements

| Your goal | Project and link | What is already implemented | My assessment |
|---|---|---|---|
| Try a complete Kinect-controlled PC game | [RunStickmanRun](https://github.com/gbaelen/RunStickmanRun) | Unity game, Kinect v1 controls, source, and a bundled Windows executable | **First game to try.** Older dependencies, but unusually complete. |
| Control games you already have | [FAAST archive](https://github.com/insertcontrollerhere/FAAST) | Configurable body gestures mapped to keyboard/mouse input | **Best low-code experiment.** Legacy toolkit, not universal game compatibility. |
| Build a reusable Unity foundation | [Kinect-SDK, Rabie Fathallah fork](https://github.com/Rabie-Fathallah/Kinect-SDK) | Updated integration based on RF Solutions’ Kinect v1 asset | **Best foundation to evaluate.** Author reports testing with Unity 6 and 2022.3. |
| Play a dance game | [JD-Kinect](https://github.com/VenB304/JD-Kinect) | Kinect v1 bridge targeting Just Dance 2017 PC’s phone-controller interface | **Experimental.** Important scoring limitations explained below. |
| Play a motion-controlled racing game on PC | [Free Riders Recompiled](https://github.com/YuutaTsubasa/Free-Riders-Recompiled) | Unofficial native PC version with physical Kinect v1 input | **Promising, but work in progress.** Requires your own game data. |
| Add head movement to compatible driving/simulation games | [KinectHeadTrackerV2](https://github.com/tensioncore/KinectHeadTrackerV2) | Kinect v1 face/head tracking forwarded to opentrack | **Useful integration project.** Head-look, not steering. |

These classifications follow the repositories’ documented hardware, deliverables, and limitations—not merely the presence of “Kinect” in their names. ([GitHub](https://github.com/gbaelen/RunStickmanRun?utm_source=chatgpt.com))

---

## 2. Existing Kinect-native PC games you can reuse

### A. RunStickmanRun — the most practical first game

**Repository:** [gbaelen/RunStickmanRun](https://github.com/gbaelen/RunStickmanRun)

This is not a conventional runner where your body directly controls the running character. The character runs automatically; you use your hands to manipulate the environment and protect him.

Its implemented controls include a right-hand cursor, gripping a hammer or shield, and a left-hand swipe that pushes the character or makes him jump. It selects the closest person as the player and also provides mouse/keyboard controls. ([GitHub](https://github.com/gbaelen/RunStickmanRun?utm_source=chatgpt.com))

**Reuse path:** the repository includes `RunStickmanRunBeta.exe`, its data directory, and supporting DLLs. Keep that distribution together when testing. For a source build, the author names Unity **2017.2.0f3**, Kinect SDK **1.8**, and scenes `Menu` and `Blocs-Assembly`. It explicitly targets **Kinect v1, not v2**. ([GitHub](https://github.com/gbaelen/RunStickmanRun?utm_source=chatgpt.com))

**My recommendation:** try the bundled build before attempting an editor upgrade. It gives you a concrete acceptance test: does the sensor connect, does a hand control the cursor, and do gestures affect gameplay?

### B. KinectWare — Pong, Arkanoid, and Marble Blast

**Repository:** [AntonFagerberg/KinectWare](https://github.com/AntonFagerberg/KinectWare)  
**Author’s demonstration page:** [KinectWare](https://www.antonfagerberg.com/projects/kinect-ware/)

The author implemented a WarioWare-inspired collection containing **Pong, Arkanoid, and Marble Blast**, controlled through body movement. The documented stack is **first-generation Kinect + Unity + ZigFu**. ([antonfagerberg.com](https://www.antonfagerberg.com/projects/kinect-ware/))

This is a good match for your “reuse existing games” requirement because the gameplay already exists. However, I verified the author’s description and source link, not a current successful build.

**My recommendation:** treat it as a gameplay donor. First assess how tightly its scripts depend on ZigFu. Where practical, retain the scenes and game mechanics while replacing only the sensor-input adapter with a working Kinect v1 Unity integration.

### C. Flappy Bird 3D and Space Walk — two games in one project

**Repository:** [VMarisevs/Gesture-Based-UI-Development-Project-2016](https://github.com/VMarisevs/Gesture-Based-UI-Development-Project-2016)

This project explicitly documents **Kinect v1**, **Unity 5.3.2f1**, and **ZigFu**. Its two games are:

| Game | Implemented interaction |
|---|---|
| **Flappy Bird 3D** | Arm flapping makes the character fly through obstacles. |
| **Space Walk** | Hands and feet interact with incoming asteroids. |

It also implements a motion-operated menu: right-hand dwell selection and a left-hand swipe to return. ([GitHub](https://github.com/VMarisevs/Gesture-Based-UI-Development-Project-2016))

**What is worth reusing:** not just the games, but the interaction flow from menu selection into gameplay.

**Caution:** its historical browser instructions involve old Unity/ZigFu web-player components. I would target a standalone Windows build rather than make that browser deployment path the foundation of your system.

### D. Fruit Ninja-style Kinect v1 game — source candidate, not yet a dependable starting point

**Repository:** [f1shuu/fruit-ninja-kinect-v1](https://github.com/f1shuu/fruit-ninja-kinect-v1)

This is explicitly presented as a **Kinect v1 Fruit Ninja project** and contains a Unity project structure, including `Assets`, `Packages`, and `ProjectSettings`. However, I did not find sufficient visible setup documentation to verify its editor version, deployment procedure, or ready-to-run status. ([GitHub](https://github.com/f1shuu/fruit-ninja-kinect-v1))

**My assessment:** worth downloading for inspection, but lower priority than RunStickmanRun. Before investing effort, check `ProjectVersion.txt`, the main scene, its Kinect dependency, and licensing. I would not describe it as a proven plug-and-play game.

### E. Microsoft Shape Game — a useful reference for two-player interaction

**Official demonstration:** [Microsoft Research: Shape Game sample](https://www.microsoft.com/en-us/research/video/demo-of-shape-game-sample-included-with-kinect-for-windows-sdk/)

Microsoft demonstrated this SDK-era game with **two people using their tracked bodies to interact with falling shapes**. It is a useful example of simple, understandable body interaction rather than an elaborate gesture vocabulary. ([Microsoft](https://www.microsoft.com/en-us/research/video/demo-of-shape-game-sample-included-with-kinect-for-windows-sdk/?utm_source=chatgpt.com))

I would use it as a reference for a two-player acceptance test, not assume that the historical demonstration is a current supported game distribution. Microsoft’s Developer Toolkit is also an official source of Kinect samples and development tools. ([Microsoft](https://www.microsoft.com/en-gb/download/details.aspx?id=40276&msockid=08cfaee40c3160681452b8020d1f613b&utm_source=chatgpt.com))

---

## 3. Playing existing PC games without rewriting them

### FAAST: the most relevant “do not reinvent the wheel” option

**Download/archive:** [insertcontrollerhere/FAAST](https://github.com/insertcontrollerhere/FAAST)

FAAST is the **Flexible Action and Articulated Skeleton Toolkit**, developed at USC’s Institute for Creative Technologies. Its purpose is to turn tracked body movement into configurable keyboard/mouse actions and to expose tracking through middleware interfaces such as VRPN. This is fundamentally different from modifying a game’s source. ([vgl.ict.usc.edu](https://vgl.ict.usc.edu/bibtexbrowser.php?bib=ICT.bib&key=suma_faast%3A_2011&utm_source=chatgpt.com))

#### Which PC games have people actually used?

**World of Warcraft:** USC published a demonstration of its tools being used to play WoW with Kinect. This is historical evidence of the approach, not verification against the present-day WoW client. ([Institute for Creative Technologies](https://ict.usc.edu/news/watch-youtube-video-showcasing-ict-tools-to-play-world-of-warcraft-with-microsoft-kinect/?utm_source=chatgpt.com))

**Final Fantasy XIV:** a creator documents using **Xbox 360 Kinect v1 + SDK 1.8 + FAAST** to play the Dancer class by physically dancing. The general setup is described publicly; the creator’s game-specific profiles are not all supplied as a free open-source package. ([CONTROLLERBEND.COM](https://controllerbend.com/pc-kinect-set-up.html))

#### How the implementation works

The reusable pipeline is:

**Kinect skeleton → configured gesture conditions → keyboard/mouse events → existing PC game.**

You configure what movement should trigger which control. The game itself does not need to understand Kinect. ([vgl.ict.usc.edu](https://vgl.ict.usc.edu/bibtexbrowser.php?bib=ICT.bib&key=suma_faast%3A_2011&utm_source=chatgpt.com))

#### How to try it

The archive documents this sequence: install SDK 1.8, connect the powered sensor, run `FAAST.exe`, change the tracker from **OpenNI to Microsoft**, click **Connect**, load or create a gesture configuration, and select **Start Emulator**. The available archive contains **FAAST 1.0**; it should not be mistaken for a modern maintained source-code SDK. ([GitHub](https://github.com/insertcontrollerhere/FAAST))

**My recommendation:** prove a few inputs in an offline game first. For example, test one movement mapped to one key, then a held action and its release. Do not begin with a complex multiplayer game or assume every title will accept synthesized input.

### JD-Kinect: Just Dance 2017 PC, with an important technical caveat

**Repository:** [VenB304/JD-Kinect](https://github.com/VenB304/JD-Kinect)  
**Implementation:** [`main.py`](https://github.com/VenB304/JD-Kinect/blob/main/main.py)

The project targets **Just Dance 2017 PC**, using Kinect v1 through SDK 1.8 and a bundled, patched PyKinect library. Its documented environment uses Python 3.10 or later. ([GitHub](https://github.com/VenB304/JD-Kinect?utm_source=chatgpt.com))

**What the code actually does:** it reads right-wrist motion, converts changes in position into scaled accelerometer-like values, and sends those through the game’s smartphone-controller protocol. The central calculation is scaled frame-to-frame displacement—not a physically measured phone accelerometer signal. ([GitHub](https://github.com/VenB304/JD-Kinect/blob/main/main.py))

That means:

> **This is a Kinect-to-phone-controller bridge, not a replacement full-body dance-scoring engine.**

The README’s broad “full-body tracking” language should not be interpreted as proof that the game evaluates your knees, feet, torso, and arms independently. The source supports a much narrower conclusion. ([GitHub](https://github.com/VenB304/JD-Kinect?utm_source=chatgpt.com))

For an isolated test environment:

```powershell
git clone https://github.com/VenB304/JD-Kinect.git
cd JD-Kinect
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Open the game’s smartphone-controller screen first. The project currently selects the first tracked skeleton, and menus still require standard controls or a phone; multiplayer and better scoring are listed as unfinished work. ([GitHub](https://github.com/VenB304/JD-Kinect?utm_source=chatgpt.com))

**My assessment:** a worthwhile experiment when you already have the PC game, but not the foundation for a dependable multi-person dance installation.

---

## 4. Racing: distinguish actual motion gameplay from head tracking

### A. Free Riders Recompiled — an actual motion-controlled racer running on PC

**Repository:** [YuutaTsubasa/Free-Riders-Recompiled](https://github.com/YuutaTsubasa/Free-Riders-Recompiled)  
**Builds:** [Releases](https://github.com/YuutaTsubasa/Free-Riders-Recompiled/releases)

Although the original title was a console game, this project runs **natively on PC**; an Xbox is not required to run the port. It is **board racing rather than car racing**.

The author explicitly reports testing physical **Kinect v1 through races on Windows**. The project also warns that it remains a work in progress, with untested or unstable areas. You must supply your own legally acquired game data; the repository does not include the game’s assets. ([github.com](https://github.com/YuutaTsubasa/Free-Riders-Recompiled))

**How it was implemented:** the project statically recompiles the original game code and supplies a replacement runtime, including a Kinect input path. It feeds sensor skeleton information into the game rather than merely mapping body movement to arrow keys. This is substantially closer to preserving a Kinect-native game’s interaction model. ([悠太翼 YUUTA TSUBASA](https://yuuta-tsubasa.studio/Free-Riders-Recompiled/?utm_source=chatgpt.com))

**Reuse approach:** start with a published Windows build and its documented Kinect setup rather than compiling the entire project first. Published releases are available. ([GitHub](https://github.com/YuutaTsubasa/Free-Riders-Recompiled/releases))

### B. KinectHeadTrackerV2 — useful for simulators, but not a steering controller

**Repository:** [tensioncore/KinectHeadTrackerV2](https://github.com/tensioncore/KinectHeadTrackerV2)  
**Receiver:** [opentrack](https://github.com/opentrack/opentrack)

Despite **“V2” in the application’s name**, this project supports **Kinect v1**. It uses face/head tracking and forwards pose information over UDP for use with opentrack. It does not turn your hands into an imaginary steering wheel. ([GitHub](https://github.com/tensioncore/KinectHeadTrackerV2))

The implementation combines a **C++/CLI tracking component** with a **Windows Forms interface**. Its build instructions require SDK 1.8 and the Face Tracking components from Developer Toolkit 1.8. They specify building `SingleFace.vcxproj` before the GUI and keeping the executable and native DLL architectures consistent. ([GitHub](https://github.com/tensioncore/KinectHeadTrackerV2/blob/master/build_readme.md))

**My assessment:** potentially a better low-fatigue use of Kinect for driving than steering with unsupported arms. Evaluate it against a game that already accepts an opentrack-compatible head-tracking interface.

### What I did not verify

I did **not** find sufficiently strong evidence in the inspected sources for a current, ready-to-run **Kinect v1 steering package with supplied profiles for Forza or Need for Speed**.

FAAST gives you a route to experiment with keyboard-controlled racing, but that is not the same as a verified, polished analogue steering integration. I would not advertise those titles as “already supported” based only on generic Kinect demonstrations.

---

## 5. Depth-based games: existing implementations beyond skeleton gestures

### A. Kinect Sandbox Driving — physical terrain becomes the driving world

**Repository:** [broaddaysk/kinectSandboxDriving](https://github.com/broaddaysk/kinectSandboxDriving)

This project is genuinely a car-driving application, but **Kinect constructs the terrain rather than steering the car**.

Its documented implementation uses Kinect v1 depth measurements, spatial and temporal smoothing, and a Unity terrain update. The terrain is refreshed approximately once per second to reduce instability. Important scripts include `modifyTerrain.cs`, `Steering.cs`, and `MouseLook.cs`. ([GitHub](https://github.com/broaddaysk/kinectSandboxDriving))

The repository documents Unity **5.5.2f1**, SDK **1.7/1.8**, and a Kinect Unity wrapper. It also includes `kinectSandboxDrivingReleaseBuild.zip`. The intended setup scans material such as sand or a deformable surface from above. ([GitHub](https://github.com/broaddaysk/kinectSandboxDriving))

**What you can reuse:** the depth-to-terrain pipeline, smoothing, and existing driving scene.

**My recommendation:** choose this for an interactive table or installation—not as evidence that a room-facing Kinect already provides hand-controlled car racing.

### B. AR Sandbox — a reusable depth-mesh and projection project

**Repository:** [jloehr/AR-Sandbox](https://github.com/jloehr/AR-Sandbox)

This Unity project supports both Kinect generations through separate paths. Its documentation specifies **SDK 1.8 for v1**, Unity **2019.1.0f2**, and a `DepthMesh` scene. For your hardware, the documented setup enables the Kinect v1 object and disables the v2 object. ([GitHub](https://github.com/jloehr/AR-Sandbox))

It is useful for terrain visualisation, projected interaction, and educational play rather than conventional TV gaming. It also introduces projector/sensor calibration work.

**My assessment:** a good second-stage project after basic tracking works. You would be reusing depth acquisition and mesh-generation logic rather than starting your own point-cloud renderer.

---

## 6. The Unity foundation I would choose

### Start with RF Solutions’ Kinect v1 integration

**Original asset:** [Kinect with MS-SDK](https://assetstore.unity.com/packages/tools/integration/kinect-with-ms-sdk-7747)  
**Documentation:** [RF Solutions](https://rfilkov.com/2013/12/16/kinect-with-ms-sdk/)  
**Recent-Unity fork:** [Rabie-Fathallah/Kinect-SDK](https://github.com/Rabie-Fathallah/Kinect-SDK)

The original package is specifically for **Kinect v1** and demonstrates avatars, gestures, overlays, and depth-based interaction. Its author directly links to the Rabie Fathallah repository for newer Unity versions. ([rfilkov.com](https://rfilkov.com/2013/12/16/kinect-with-ms-sdk/))

The fork describes itself as tested with **Unity 6 and Unity 2022.3**. That is author-reported compatibility, not something I independently reproduced. Nevertheless, it is a much better starting lead than assuming every Kinect v1 project must remain on Unity 4 or 5. ([GitHub](https://github.com/Rabie-Fathallah/Kinect-SDK))

Useful example scenes in the original package include:

| Scene | What it lets you validate |
|---|---|
| `KinectAvatarsDemo` | Skeleton-driven avatar movement |
| `KinectGesturesDemo` | Gesture detection |
| `KinectOverlayDemo` | Alignment of tracked content and the camera view |
| `DepthColliderDemo` | Interaction based on depth geometry |

These are integration examples, not a finished collection of party games. ([rfilkov.com](https://rfilkov.com/2013/12/16/kinect-with-ms-sdk/))

### How I would reuse this across several games

My proposed approach is to keep **one validated sensor-input layer**, then adapt games to consume its outputs.

For a gesture game, pass recognised actions such as jump, swipe, or select. For a hand-interaction game, pass tracked hand positions. For a terrain game, pass depth data. Preserve the existing gameplay rather than rebuilding all projects around one enormous framework.

For the older ZigFu projects, first determine whether the dependency is confined to a few scripts. A small input adapter may be practical; a deeply coupled project may cost more to port than it is worth.

**Do not start by developing skeleton estimation from point clouds.** The existing SDK and Unity integrations already provide the relevant tracking and examples. Your engineering effort is better spent on integration, user interaction, and repeatability. ([Microsoft](https://www.microsoft.com/en-us/download/details.aspx?id=40278))

---

## 7. Establish a working PC baseline before opening game projects

### Official downloads

**SDK:** [Kinect for Windows SDK 1.8](https://www.microsoft.com/en-us/download/details.aspx?id=40278)  
**Tools and samples:** [Kinect for Windows Developer Toolkit 1.8](https://www.microsoft.com/en-us/download/details.aspx?id=40276)

Microsoft’s installation instructions say to install the SDK with the sensor disconnected, remove conflicting Kinect drivers where necessary, then connect external power and USB. The SDK supplies the drivers and APIs; the Developer Toolkit supplies additional tools and source samples. Microsoft lists a dedicated USB 2.0 bus in the hardware requirements. ([Microsoft](https://www.microsoft.com/en-us/download/details.aspx?id=40278))

**Important OS caveat:** the official SDK page lists Windows 7, 8, and 8.1—not Windows 11. Community projects may report operation on newer Windows versions, but that does not create an official compatibility guarantee. ([Microsoft](https://www.microsoft.com/en-us/download/details.aspx?id=40278))

I would use this validation order:

1. **Sensor first:** confirm colour/depth and skeleton tracking in a Microsoft sample.
2. **Known game second:** try one existing executable without changing its dependencies.
3. **Unity third:** validate the integration’s own demo scenes before importing game code.
4. **Upgrade last:** preserve a working copy before changing editors, packages, or native plugins.

This isolates hardware/driver failures from game and editor failures. I would not disable Windows security protections or change operating systems merely because an old forum post suggests it.

### Avoid three common mismatches

**Kinect v1 versus v2:** SDK 2.0 and PyKinect2 are not replacements for the v1 stack. For example, the popular-looking BorderEscape project explicitly uses Kinect 2.0, so it is not a drop-in game for your sensor. ([GitHub](https://github.com/Kinect/PyKinect2?utm_source=chatgpt.com))

**Multiple driver stacks:** do not install Microsoft, OpenNI/NiTE, and assorted legacy packages indiscriminately. RF Solutions’ troubleshooting history explicitly describes conflicting installations and recommends a clean SDK 1.8 configuration for the reported failure. ([rfilkov.com](https://rfilkov.com/2013/12/16/kinect-with-ms-sdk/))

**Native DLL architecture:** an x64 game/editor needs compatible native components. The head-tracker build documentation specifically identifies architecture mismatches as a launch-failure cause. ([GitHub](https://github.com/tensioncore/KinectHeadTrackerV2/blob/master/build_readme.md))

---

## 8. What matters for your room installation

### “It sees several people” does not mean “all can play”

With the **Microsoft Kinect v1 SDK**, distinguish detection of up to six people from detailed tracking of **two active players**. Do not plan a four-to-six-player full-skeleton game around that SDK capability. ([Microsoft Learn](https://learn.microsoft.com/en-us/archive/msdn-magazine/2012/april/kinect-context-aware-dialogue-with-kinect?utm_source=chatgpt.com))

Application limits can be narrower still: RunStickmanRun chooses the closest person, while JD-Kinect currently selects the first tracked skeleton. A sensor’s two-player capability does not automatically make either application multiplayer. ([GitHub](https://github.com/gbaelen/RunStickmanRun?utm_source=chatgpt.com))

### Validate the high mount after the software works

For your earlier proposed mount above the TV, my recommendation is to establish a normal front-facing baseline first, then test the intended mounting position.

At the final position, record whether hands and feet remain tracked throughout actual gameplay, whether one person hides another, and whether the application switches players when someone walks through the room. Treat these as acceptance tests, not assumptions based on the camera preview.

Also separate the room-facing and tabletop use cases: the sandbox projects have a different sensing geometry and purpose from a standing body-tracking game.

### Public source is not automatically reusable source

Check each project’s licence before incorporating it into a shared or commercial product. GitHub explains that a repository without a licence does not automatically grant permission to reproduce, distribute, or create derivative works. ([GitHub Docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository))

The RF Solutions asset is listed under the **Unity Asset Store EULA**. A third-party GitHub fork does not, by itself, remove the original asset’s licensing conditions. Review code, third-party plugins, and game assets separately. ([assetstore.unity.com](https://assetstore.unity.com/packages/tools/integration/kinect-with-ms-sdk-7747))

---

## 9. My recommended reuse plan

For your team, I would run **three small evaluations in parallel**, rather than start by rebuilding a complete gaming platform:

| Evaluation | Starting point | Success criterion I would use |
|---|---|---|
| **Complete game** | RunStickmanRun | A player can enter, interact, lose tracking briefly, and resume without restarting. |
| **Existing PC-game control** | FAAST | Several mapped actions work reliably, including key release and stopping input when tracking is lost. |
| **Reusable Unity integration** | RF Solutions examples / Rabie fork | Tracking, gestures, and a standalone build work on the same PC configuration. |

After those pass, choose **KinectWare or Flappy Bird/Space Walk** for more game mechanics, **JD-Kinect** for an experimental dance bridge, or **the sandbox projects** for depth-based installations.

For each successful setup, preserve the repository commit, editor version, SDK version, native DLLs, configuration, and a short test recording. That becomes your reproducible baseline.

**My bottom line:** start by **running RunStickmanRun, configuring FAAST, and validating the recent-Unity Kinect v1 integration**. Those three experiments give you the clearest route to reuse: one complete game, one way to control existing games, and one foundation for adapting additional source projects—without first rebuilding tracking or gesture recognition.


---

<a id="part-iii"></a>
# Part III — Fixed Kinect v1 scanning research


## Images:
![Kinect 3D Scanner Platform by Xypher2000 - Thingiverse](https://images.openai.com/static-rsc-4/LefAnfXKR5cVp6XAPKrnwG8b-Z_PzrACjn0K2t6bOn7JNlzn2DVZJHVCHwRaQvghaznNv6U4lTmxpz3xoIQuXwBZRfaQBDPrsIv1H9Oq9Tbo2LFp-bjHfmWliytlvcz_oKM2ZNfT12cA2tEb1mbPhCJLn7kKAEoliTyJz3aprZw?purpose=inline)


# Kinect v1 as a fixed 3D scanner: what to reuse, how to scan, and what accuracy to expect

Karthi, **your Kinect v1 can become a useful fixed-position PC scanning station without building a reconstruction engine from scratch.** Existing software supports rotating-object scans, self-scanning, point-cloud generation, and mesh export.

The strongest options I found are **RecFusion for a packaged commercial workflow, ReconstructMe for a free non-commercial starting point, and existing Kinect/Open3D projects for custom automation**. Both commercial applications explicitly document the rotating-subject approach relevant to your fixed camera. ([RecFusion - 3d Reconstruction Software](https://www.recfusion.net/products/?utm_source=chatgpt.com))

However, one distinction determines the whole design:

> **A fixed Kinect can measure the surfaces it sees. To measure the back, sides, or underside, those surfaces must become visible—usually by rotating or repositioning the subject. Making a mesh watertight does not mean its previously hidden surfaces were measured.**

Below, I separate working application workflows from source-code starting points and experimental repositories. I checked documentation and repository contents, but **I have not run these applications with your physical Kinect or verified their accuracy on your PC**.

**Research checked: November 17, 2026.**

---

## 1. What your fixed-camera setup can actually deliver

There are three useful operating modes—not one universal “scan everything completely” mode.

| Operating mode | Camera and subject | Useful result | Important limitation |
|---|---|---|---|
| **Live 3D capture / snapshot** | Both remain stationary | Point cloud of visible surfaces; distances between visible points; surface profiles | Back surfaces and occluded areas remain unknown |
| **360° reconstruction** | Camera stationary; object or person rotates | Combined multi-view point cloud and mesh | Tracking must follow the rotating subject, not the stationary room |
| **More complete object reconstruction** | Camera stationary; object rotates, then is repositioned for additional scans | Sides plus additional top/underside coverage | Separate scans need overlapping geometry for alignment |

The second mode is already documented in ReconstructMe and RecFusion. Their guidance is particularly important: **exclude stationary background geometry from the reconstruction region when the object rotates**. Otherwise, registration can follow the wall or table while the object moves independently. ([ReconstructMe](https://www.reconstructme.net/qa_faqs/how-can-i-improve-the-quality-of-my-scanning-results/?utm_source=chatgpt.com))

For your requirements, I would implement two distinct functions:

**“Capture visible geometry”** for quick measurements and point-cloud export.

**“Scan complete object”** for a guided rotation sequence, followed by optional additional orientations.

That keeps the user interface honest about what has actually been observed.

---

## 2. The software shortlist I would use

| Tool | Kinect v1 fit | What you can reuse | Recommendation |
|---|---|---|---|
| **[RecFusion](https://www.recfusion.net/products/)** | Officially lists Xbox 360 Kinect | Reconstruction, recording, cleanup, saved workspaces, mesh and point-cloud export | **Strongest documented packaged candidate** |
| **[ReconstructMe](https://www.reconstructme.net/)** | Documents first-generation Kinect workflows | Object scanning, turntable workflow, self-scanning, standard mesh exports | **First free non-commercial experiment** |
| **[FaceFusion](https://github.com/JoshBlake/facefusion)** | Specifically targets Kinect for Windows v1 | Fixed-camera head isolation and reconstruction | **Best directly relevant self-scan source project** |
| **[ObjectDimensions_from_Kinectv1](https://github.com/Atif-Anwer/ObjectDimensions_from_Kinectv1)** | Explicitly Kinect v1/Xbox 360 | MATLAB GUI for measuring objects in RGB-D images | **Useful measurement reference, not a complete scanner** |
| **[libfreenect](https://github.com/OpenKinect/libfreenect) + [Open3D](https://github.com/isl-org/Open3D)** | v1 acquisition plus generic 3D processing | Capture, filtering, registration, fusion, meshing, file export | **Best modular route for your own automated station** |
| **[Ghostlight](https://github.com/Dom-Tursini/Ghostlight)** | Explicitly original Xbox Kinect | Modern Windows/CUDA scanning pipeline | **Experimental; important turntable limitations remain** |
| **[Skanect](https://support.structure.io/article/457-where-can-i-find-skanect-download-link)** | v1 listed as unofficial hardware | Established scanning and post-processing workflow | **Fallback, not my first new dependency** |

The distinctions matter: Skanect is now labelled **retired**, and its current driver documentation does not guarantee Kinect compatibility. Ghostlight’s author explicitly describes unfinished or broken functionality. Neither should be presented as an unquestionable plug-and-play solution. ([Structure Support](https://support.structure.io/article/374-what-sensor-drivers-should-i-install))

---

## 3. The packaged solution: fixed Kinect + rotating product + RecFusion

### Why this is worth evaluating first

RecFusion explicitly lists **Kinect v1 / Xbox 360 Kinect**, with **Kinect SDK 1.8** as its driver requirement. It supports recording RGB-D sequences, reconstruction, mesh cleanup, and exports including **STL, OBJ, PLY, PCD, and XYZ**. Its standard edition is for one sensor; Pro adds multi-sensor operation. ([RecFusion - 3d Reconstruction Software](https://www.recfusion.net/products/?utm_source=chatgpt.com))

The [official download page](https://www.recfusion.net/download-recfusion/) currently lists **RecFusion 2.3.0 for 64-bit Windows**. The evaluation version allows testing reconstruction but **does not allow exporting the result**. ([RecFusion - 3d Reconstruction Software](https://www.recfusion.net/download-recfusion/?utm_source=chatgpt.com))

There is also a purchasing caveat: the [purchase page](https://www.recfusion.net/purchase/) lists **€199 including 19% VAT** for the single-sensor edition, but says the webshop is unavailable and purchases require direct contact. Treat that as the published listing, not a confirmed quote for your location. ([RecFusion - 3d Reconstruction Software](https://www.recfusion.net/purchase/))

### The station I would set up

For the first experiment, I recommend a **matte, rigid, asymmetric object approximately 20–50 cm across**, on a stable rotating platform. This is my proposed test object—not a manufacturer-specified minimum size.

Keep the Kinect fixed and bring the object into its usable view. Avoid starting with a tiny figurine, transparent bottle, polished metal part, or a perfectly symmetric cylinder. ReconstructMe’s scanning guidance specifically identifies insufficient geometric features, symmetry, unsuitable lighting, and excessive movement as tracking problems. ([ReconstructMe](https://www.reconstructme.net/qa_faqs/how-can-i-improve-the-quality-of-my-scanning-results/?utm_source=chatgpt.com))

### The existing application workflow

RecFusion’s documented workflow is:

1. Select the sensor and inspect its colour, depth, and point-cloud views.
2. Position and size the reconstruction volume around the subject, excluding non-rotating surroundings.
3. Save the configuration as a workspace.
4. Start reconstruction and rotate the subject slowly while monitoring tracking status.
5. Finish, clean the result, and use **Save Mesh** in a licensed version.

It also supports delayed/timed capture and recording sequences for later reconstruction. Those are useful for a repeatable fixed station because you can retry processing without asking the person to repeat every scan. ([RecFusion - 3d Reconstruction Software](https://www.recfusion.net/user-guide/))

**My recommendation:** test sensor recognition and a complete rotation in evaluation mode before considering a licence. Do not purchase on the assumption that old Kinect drivers and your current Windows/GPU combination will work perfectly.

### Getting the underside

A horizontal rotation cannot reveal a surface resting on the platform. My proposed procedure is to scan the object upright, reposition it to expose the underside, and capture a second session with substantial overlap.

Use [CloudCompare’s point-pair alignment](https://www.cloudcompare.org/doc/wiki/index.php?title=Align) to initialise the relationship between scans, then refine with registration. This is an existing tool workflow; you do not need to implement alignment from scratch. ([cloudcompare.org](https://www.cloudcompare.org/doc/wiki/index.php?title=Align&utm_source=chatgpt.com))

Do not expect this to reveal inaccessible internal cavities. Some surfaces simply cannot be observed from the available viewpoints.

---

## 4. The free starting point: ReconstructMe

**Official site:** [ReconstructMe](https://www.reconstructme.net/)  
**Capabilities:** [Product overview](https://www.reconstructme.net/reconstructme-ui/)

ReconstructMe documents metric reconstruction and exports such as **STL, OBJ, and PLY**. Its published terms describe free use for **private/non-commercial purposes**; do not assume that automatically covers a company product or commercial service. ([ReconstructMe](https://www.reconstructme.net/reconstructme-ui/?utm_source=chatgpt.com))

For your project, it has two particularly relevant workflows.

### A. Fixed-camera product scanning

The developer published a [turntable-scanner implementation](https://www.reconstructme.net/a-simple-turntable-scanner-with-reconstructme/), including a marker-based way to establish the reconstruction volume.

The marker establishes a useful coordinate frame and lets the volume begin above the platform, excluding the stand and floor. Importantly, that article says marker-based tracking was **not** being used in the demonstrated implementation. Do not confuse “marker positions the volume” with “marker guarantees accurate rotation tracking.” ([ReconstructMe](https://www.reconstructme.net/a-simple-turntable-scanner-with-reconstructme/))

This is directly reusable knowledge for your setup: **get foreground isolation and volume placement right before developing a new tracker.**

### B. Fixed-camera self-scanning

The [official Selfie instructions](https://www.reconstructme.net/qa_faqs/how-do-i-create-a-3d-selfie/) describe placing the camera near eye level, selecting **Selfie mode** under Surface settings, using **Suggest Defaults**, and rotating through a full turn. The application then prepares a printable bust. A start delay and sound feedback help when scanning alone. ([reconstructme.net](https://www.reconstructme.net/qa_faqs/how-do-i-create-a-3d-selfie/?utm_source=chatgpt.com))

**Critical measurement warning:** Selfie mode scales the saved model to **20 cm tall**. Therefore, that output is suitable for a miniature bust, **not for preserving your original body dimensions**. For measurement, use a metric reconstruction workflow without automatic resizing and independently verify the exported scale. ([ReconstructMe](https://www.reconstructme.net/faq-category/scanning/?utm_source=chatgpt.com))

For a first trial, I would scan a **head-and-shoulders bust before attempting a full body**. That reduces the area you need to cover and makes it easier to inspect the result.

---

## 5. The most relevant GitHub implementations

### A. FaceFusion: the closest match to “I stand in front of a fixed Kinect and scan myself”

**Repository:** [JoshBlake/facefusion](https://github.com/JoshBlake/facefusion)

This project uses **Microsoft Kinect Fusion**, automatically isolates the head, and reconstructs it as the person turns in front of a stationary sensor. It includes voice control, audio feedback for scan progress, and **OBJ export**.

The repository contains `FaceFusion.sln` and the associated Kinect Toolkit components. Its stated requirements are Kinect for Windows, SDK **1.7 or later**, and a DirectX 11-compatible GPU.

The important limitations are unusually well documented: head and shoulders should move together when both are included; full-turn scans may have a seam; and additional tilting is needed to expose the crown and areas under the chin. It is MIT-licensed, but it is an old application, not a verified current-Windows build. Also, its explicit hardware requirement is **Kinect for Windows v1**, so do not assume every close-range setting works unchanged on an Xbox 360 sensor. ([GitHub](https://github.com/JoshBlake/facefusion))

**My assessment:** the strongest source-code reference for a guided self-scanning experience.

### B. ObjectDimensions_from_Kinectv1: existing product measurement code

**Repository:** [Atif-Anwer/ObjectDimensions_from_Kinectv1](https://github.com/Atif-Anwer/ObjectDimensions_from_Kinectv1)

This is a MATLAB implementation associated with a research paper on calculating real-world object dimensions from Kinect RGB-D images.

The GUI loads RGB and depth images; the user selects object corners in a defined order. Useful files include:

`GUI_DepthResolution_v4.m`, `ftnCalcDepthResolution.m`, and `ftnDepth2meters.m`.

The authors specify Kinect v1/Xbox 360 data, MATLAB 2014b or later, and testing on named TUM RGB-D sequences. The repository is GPL-3.0.

**What it does not provide:** automatic product recognition, a complete live capture application, or 360° mesh reconstruction. It is an offline measurement implementation that you can study or adapt. ([GitHub](https://github.com/Atif-Anwer/ObjectDimensions_from_Kinectv1))

**My assessment:** useful for validating a dimensioning approach, but not a replacement for a scanning application.

### C. Ghostlight: promising modernisation, but not the dependable turntable solution yet

**Repository:** [Dom-Tursini/Ghostlight](https://github.com/Dom-Tursini/Ghostlight)

Ghostlight targets original Kinect hardware on Windows with an Nvidia/CUDA reconstruction pipeline. It includes raw recording, later re-fusion, registration, mesh extraction, and geometry export.

However, its own documentation identifies unreliable turntable/floor removal and volume placement, tracking problems, and turntable-axis functionality that is not yet connected into the complete workflow. Colour export has also been removed from the interface because of quality problems.

**My assessment:** valuable code to inspect, particularly for modern acquisition/reconstruction separation. I would not make it your first acceptance-test application, because the unfinished areas overlap your exact fixed-turntable requirement. ([GitHub](https://github.com/Dom-Tursini/Ghostlight?utm_source=chatgpt.com))

### D. Other source projects worth knowing

| Repository | Existing implementation | How I would use it |
|---|---|---|
| **[MichalZak17/Kinect-3D-Scanner](https://github.com/MichalZak17/Kinect-3D-Scanner)** | Kinect v1 acquisition, PyQt interface, FastAPI server, Open3D registration/fusion, PLY/OBJ export | Reference for a modular scanning service. Its documented workflow moves the camera, so fixed-turntable suitability is not established. ([GitHub](https://github.com/MichalZak17/Kinect-3D-Scanner)) |
| **[chrdiller/KinectFusionLib](https://github.com/chrdiller/KinectFusionLib)** | C++/CUDA reconstruction library with point-cloud and mesh output | Reuse the reconstruction engine when you need C++ control; it is not a packaged sensor application. ([GitHub](https://github.com/chrdiller/KinectFusionLib)) |
| **[rgbdemo/rgbdemo](https://github.com/rgbdemo/rgbdemo)** | Historical RGB-D tools, including `scan-topview` and `scan-markers` | Study earlier scanning approaches; the repository is archived and explicitly unmaintained. ([GitHub](https://github.com/rgbdemo/rgbdemo)) |

**I would not start by porting a Kinect v2 scanner.** For example, `letrend/kinect_scanner` has attractive turntable functionality, but explicitly targets **Kinect v2**. Its existence does not make it a drop-in solution for your v1. ([GitHub](https://github.com/letrend/kinect_scanner?utm_source=chatgpt.com))

---

## 6. For your own automated station, reuse this architecture

**Unity is not necessary for scanning.** My recommendation is to validate an existing application first, then build automation around an established capture and reconstruction stack only where needed.

A suitable architecture is:

```text
Fixed Kinect v1
      │
      ▼
SDK 1.8 OR libfreenect
      │
      ▼
Depth + calibration + optional RGB
      │
      ▼
Valid-depth filtering + scan-region selection
      │
      ├── Snapshot mode
      │      └── Visible point cloud → measurements → PLY/PCD/XYZ
      │
      └── Rotating-subject mode
             └── Relative-pose estimation
                    → multi-view fusion
                    → point cloud / mesh
                    → measurement copy
                    → separately repaired print copy
```

### Acquisition: reuse libfreenect or Microsoft’s v1 stack

[libfreenect](https://github.com/OpenKinect/libfreenect) is the OpenKinect driver library for the original Kinect. It exposes depth and other sensor streams; it is **not itself a complete reconstruction system**. It also includes recording/replay facilities useful for repeatable development. Do not substitute `libfreenect2`, which targets the later sensor. ([GitHub](https://github.com/OpenKinect/libfreenect))

On Windows, the [Microsoft Developer Toolkit 1.8](https://www.microsoft.com/en-us/download/details.aspx?id=40276) includes Kinect Fusion development material. The Fusion API already provides operations for frame integration, point-cloud calculation, and mesh extraction. ([Microsoft](https://www.microsoft.com/en-gb/download/details.aspx?id=40276&msockid=1f27d15948ea680c0d07c78149b86986&utm_source=chatgpt.com))

Choose one working acquisition path first. Changing USB driver bindings for an alternative stack can affect applications expecting Microsoft’s driver.

### Geometry processing: reuse Open3D

Open3D already provides depth-to-point-cloud conversion, filtering, plane segmentation, registration, and bounding-volume operations. Its reconstruction tutorials also demonstrate TSDF integration—a method that combines multiple depth observations into a common volumetric surface representation. ([open3d.org](https://www.open3d.org/docs/release/python_api/open3d.geometry.PointCloud.html))

The implementation work remaining is principally **connecting your v1 frames, calibration, foreground mask, and relative poses correctly**. That is integration work, not a reason to reimplement ICP, fusion, meshing, or file writers.

### The crucial fixed-camera implementation detail

**Do not give every frame an identity pose merely because the physical camera is fixed.**

When the product rotates, its pose relative to the camera changes. Fusion must compensate for that motion in an object-centred reference frame. Otherwise, different sides will be integrated into inconsistent positions. Open3D’s integration example explicitly requires a trajectory/pose for its observations. ([open3d.org](https://www.open3d.org/docs/release/tutorial/pipelines/rgbd_integration.html))

My suggested progression is:

**First:** let an existing scanner estimate relative motion from the isolated object.

**Later, if repeatability requires it:** add a calibrated turntable axis and known angular positions to constrain alignment.

A printed pattern helps only when the chosen software actually uses it. A depth-only geometric tracker cannot obtain extra 3D shape from a flat printed texture.

---

## 7. Measuring product geometry: what to calculate and what not to assume

### Visible-point measurements are straightforward

For calibrated pinhole depth data, back-projection has the familiar form:

\[
X=\frac{(u-c_x)Z}{f_x},\qquad
Y=\frac{(v-c_y)Z}{f_y}
\]

Here, \(Z\) must use the correct depth scale, and the intrinsics must correspond to the depth image being processed. Open3D exposes this conversion directly. For Kinect data, use appropriate calibration/mapping rather than copying generic focal-length constants from a tutorial. ([open3d.org](https://www.open3d.org/docs/release/python_api/open3d.geometry.PointCloud.html))

The distance between two reconstructed points is then ordinary Euclidean distance. [CloudCompare’s point-picking tool](https://cloudcompare.org/doc/wiki/index.php/Point_picking) already supports such measurements. ([cloudcompare.org](https://cloudcompare.org/doc/wiki/index.php/Point_picking?utm_source=chatgpt.com))

### Overall dimensions require a defined reference frame

For a repeatable product station, I would establish the support plane and measurement axes once, then measure each segmented object in that coordinate frame.

A useful processing sequence is:

**Exclude invalid depth → isolate product → remove support/background → remove outliers → fit relevant surfaces or measure extents.**

Open3D already supplies plane segmentation and point-cloud filtering. However, an automatic bounding box is not automatically the same thing as the product’s intended engineering length, width, and height. The definition of those dimensions remains part of your application. ([open3d.org](https://www.open3d.org/docs/latest/tutorial/geometry/pointcloud.html?utm_source=chatgpt.com))

### A single view can give misleading “complete dimensions”

Consider a bottle viewed from the front. The measured cloud contains visible surface points, not the entire bottle. A bounding box around those points is therefore not proof of the bottle’s complete depth.

A known cuboid can sometimes be measured using visible faces and explicit shape assumptions. An arbitrary irregular product requires additional views. **Label model-based assumptions separately from observed geometry.**

Similarly, distinguish a volume estimate above a known plane from the volume enclosed by a complete 3D surface. CloudCompare provides separate approaches for these cases; a closed-mesh volume calculation requires appropriate closed geometry. ([cloudcompare.org](https://cloudcompare.org/forum/viewtopic.php?t=2893&utm_source=chatgpt.com))

---

## 8. Accuracy: useful scanning, not automatic precision metrology

Kinect v1 accuracy changes with distance and acquisition conditions. A foundational empirical study reported random depth errors growing from **a few millimetres to approximately 4 cm near the maximum tested range**. That is evidence against assuming a single universal accuracy number. ([PubMed](https://pubmed.ncbi.nlm.nih.gov/22438718/?utm_source=chatgpt.com))

ReconstructMe’s own historical guidance gives an approximate **5–8 mm accuracy on a 0.5 m part under ideal conditions**, while explicitly separating reconstruction resolution from accuracy. That is a vendor rule of thumb, **not a certified tolerance for your sensor or station**. ([ReconstructMe](https://www.reconstructme.net/support-faq/category-scanning/?utm_source=chatgpt.com))

My engineering assessment is therefore:

| Intended use | Suitability of your Kinect v1 |
|---|---|
| Printable busts and decorative models | Good starting application |
| Rough product envelopes and spatial fit | Worth evaluating against your tolerance |
| Cosplay/body reference meshes | Useful, with scale and pose checks |
| Coarse shape comparison or educational digitisation | Reasonable |
| Small threads, gear teeth, snap-fit details, submillimetre inspection | Not a dependable target |
| Measurements used for safety-critical or clinical decisions | Not justified without application-specific validation |

These are recommendations based on the documented limitations, not results from testing your hardware.

### How I would validate your station

Before scanning people or valuable products, use several matte reference objects with independently known dimensions.

For each, capture **five independent scans** at the intended distance. Compare dimensions before aggressive smoothing or hole filling, and record the spread as well as average error. Repeat at different positions within the scan region.

Set a pass criterion based on the actual task. For example, a proposed ±5 mm requirement must be **demonstrated by those tests**, not assumed because you selected a 1 mm reconstruction voxel.

Also preserve the original data. Smoothing, simplification, and surface completion can improve appearance while changing measurements.

---

## 9. Your mounting position: one fixed location creates trade-offs

Your earlier plan placed the sensor high above the TV. I would **not finalise that mount before proving the scanning geometry**.

A head scanner benefits from a view near head height. A tabletop product benefits from a close view aimed at the product. A full-body scanner needs enough vertical coverage. FaceFusion’s author specifically recommends approximately head-height placement for its self-scan workflow. ([GitHub](https://github.com/JoshBlake/facefusion))

Kinect v1’s documented field of view is approximately **57° horizontal × 43° vertical**. ([Microsoft Learn](https://learn.microsoft.com/en-us/archive/msdn-magazine/2012/april/kinect-context-aware-dialogue-with-kinect?utm_source=chatgpt.com))

Using that vertical angle, the idealised visible height at distance \(d\) is:

\[
H=2d\tan(43^\circ/2)\approx0.79d
\]

Thus, at 2.5 m the vertical span is approximately 1.97 m; at 3 m it is about 2.36 m. These are geometric estimates, not guaranteed usable full-body scan dimensions. Tilt, subject position, and edge margins matter.

**My proposed arrangement:** keep the Kinect fixed during each scan, but initially use an adjustable mount while validating three positions: product, bust, and full body. Once you decide which mode matters most, lock down the permanent position.

A permanently high, room-wide view is a poor compromise for capturing small product detail. Bring products to a stable scanning position rather than simply holding them somewhere in the room.

### Two body-scanning precautions

A person is not a rigid object: posture changes and independent movement of the head, shoulders, or arms can break the rigid reconstruction assumption. FaceFusion specifically documents failure when the head and included shoulders move independently. ([GitHub](https://github.com/JoshBlake/facefusion))

For full-body rotation, use a safe method. Do not stand on a small tabletop turntable or an improvised platform. Start with a seated bust or carefully controlled standing turn; any powered human platform should be properly load-rated.

---

## 10. Exporting STL, PLY, OBJ, and other formats

**Point-cloud export and mesh export are different operations.** Renaming a point-cloud file to `.stl` does not create a printable surface.

| Format | What to use it for | Important qualification |
|---|---|---|
| **PLY** | Point clouds or triangle meshes; can preserve colour | Check whether the file contains points, faces, or both |
| **PCD / XYZ** | Measurement and point-cloud processing | Not directly a solid printable model |
| **OBJ** | Mesh interchange and visualisation | Texture/material export depends on the application |
| **STL** | Broad 3D-printing compatibility | Triangle geometry; no standard unit declaration |
| **GLB / glTF** | Convenient visualisation and sharing | Depends on exporter support |
| **3MF** | Manufacturing/printing exchange with explicit units | Usually a conversion step from the scanning output |

Open3D documents separate point-cloud and triangle-mesh I/O. RecFusion also distinguishes its supported model exports, while 3MF explicitly includes unit information that STL lacks. ([open3d.org](https://www.open3d.org/docs/release/tutorial/geometry/file_io.html))

For your station, I recommend preserving **two deliverables**:

**Measurement copy:** original-scale point cloud or minimally processed mesh, together with calibration and capture settings.

**Printing copy:** repaired mesh, with intentional hole filling, base creation, simplification, and any requested scaling.

[MeshLab](https://www.meshlab.net/) provides existing mesh-processing and preparation tools. Open3D also implements surface reconstruction, including Poisson reconstruction. Neither algorithm makes unobserved geometry become measured evidence. ([MeshLab](https://www.meshlab.net/?utm_source=chatgpt.com))

Before sending an STL to a slicer, check a known dimension after import. A metre/millimetre mismatch can produce a model at the wrong scale even when the reconstruction itself was metric.

For **STEP or an editable CAD solid**, plan a separate reverse-engineering operation: fitting planes, cylinders, profiles, and design features to the scan. That is not equivalent to exporting the same triangles under another filename.

---

## 11. What actual users have done—and what their failures teach us

I checked community examples as evidence of use, while using developer documentation for the technical conclusions.

### Body scans used to fit another model

A [2024 Reddit post](https://www.reddit.com/r/3Dprinting/comments/1gcrzz7) describes buying Kinect v1, scanning, and deforming another model to fit the captured body geometry. That is a productive application: using the scan as a fit/reference surface rather than demanding precision reproduction of every detail. It remains a user report, not an accuracy validation. ([Reddit](https://www.reddit.com/r/3Dprinting/comments/1gcrzz7?utm_source=chatgpt.com))

### The rotating object disappears or fails to reconstruct

A [turntable discussion](https://www.reddit.com/r/3DScanning/comments/15hl7pf) describes this class of problem. The developer guidance provides the reliable explanation: a stationary background and rotating foreground do not form one rigid scene. Excluding the background is essential; cropping it out only after a bad reconstruction is too late. ([Reddit](https://www.reddit.com/r/3DScanning/comments/15hl7pf?utm_source=chatgpt.com))

### Old tutorials lead to retired software

A [2025 Skanect discussion](https://www.reddit.com/r/3DScanning/comments/1j889ro/skanect_2025_and_after/) captures the difficulty of reviving a Kinect after the surrounding software ecosystem changes. The official documentation confirms that Skanect is retired and Kinect is now an unofficial, unsupported sensor option. Use official downloads, and do not treat community redistribution of installers as automatically trustworthy. ([Reddit](https://www.reddit.com/r/3DScanning/comments/1j889ro/skanect_2025_and_after/?utm_source=chatgpt.com))

The recurring lesson is that **driver compatibility, object isolation, tracking stability, and scale preservation matter more than finding another repository with “3D scanner” in its title.**

---

## 12. The implementation plan I recommend for you

### First: establish the Kinect v1 baseline

Install [Kinect SDK 1.8](https://www.microsoft.com/en-us/download/details.aspx?id=40278) and, for sample tools, [Developer Toolkit 1.8](https://www.microsoft.com/en-us/download/details.aspx?id=40276). Confirm valid depth before troubleshooting any scanner.

Microsoft’s original SDK compatibility list names Windows 7/8/8.1, not Windows 11, so test on your actual machine rather than assuming official modern-OS support. Also distinguish the Xbox 360 sensor from Kinect for Windows v1: the latter has Near mode; the Xbox sensor does not. ([Microsoft](https://www.microsoft.com/en-in/download/details.aspx?id=40278&utm_source=chatgpt.com))

### Second: prove the fixed product-scanning workflow

Use **ReconstructMe for a non-commercial test** or **RecFusion evaluation**. Scan one suitable rigid object through a rotation. Require a stable reconstruction, inspect the seam, and determine whether the geometry is useful before adding automation.

For a no-cost file-export experiment, ReconstructMe is the more direct starting point; RecFusion’s evaluation deliberately disables export. ([ReconstructMe](https://www.reconstructme.net/blog/?utm_source=chatgpt.com))

### Third: prove measurement, not just appearance

Export a metric result, inspect it in CloudCompare, and compare it with independently known dimensions. Keep the scan unchanged until those checks are complete.

Only then create a separate printable STL using existing mesh-cleanup tools. ([cloudcompare.org](https://cloudcompare.org/doc/wiki/index.php/Point_picking?utm_source=chatgpt.com))

### Fourth: add self-scanning and automation

Evaluate ReconstructMe’s bust workflow, remembering its automatic resizing. Study **FaceFusion** for guidance, subject isolation, and audio feedback. Add a custom **libfreenect/SDK + Open3D** application only for requirements the packaged workflow does not meet—such as automatic product selection, batch measurements, repeatable capture, or integration with another system.

**My final recommendation:** build a **fixed Kinect v1 station with controlled subject rotation**, not a general “point at anything and recover its complete hidden geometry” system. Start with **ReconstructMe or RecFusion for acquisition/reconstruction, CloudCompare for measurement, and MeshLab for the printing copy**. That reuses the difficult work already implemented and leaves your team to solve the application-specific parts: positioning, segmentation, validation, and automation.


---

<a id="appendix-a"></a>
# Appendix A — Original research-launch response

I've started **Deep Research** on Kinect-style depth sensors, focusing on your proposed living-room setup with the sensor mounted 6–7 feet above the TV.

The research will investigate real-world productivity applications, multiplayer motion-controlled games (including racing), point-cloud interaction projects, and the technical feasibility of connecting these sensors to a PS5.

It will also compare Kinect with modern depth cameras, examine open-source projects and community experiments, and identify overlooked applications.

The final report will include **source links, hardware recommendations, installation considerations, compatibility limitations, and a practical implementation roadmap**\.

You can follow the research progress in the Deep Research panel.

---

<a id="appendix-b"></a>
# Appendix B — Original user requests

## Original request: broad research

[$deep-research](app://connector_openai_deep_research) Make a deep research with how people are using like Kinect based sensor in their day-to-day life and making their productivity level go high. And I also want to know like what all the games there can be played.The game should be, like I'm planning to mount the Kinect sensor on top of the room. So it should be like six to seven feet on top of the TV. So it will be facing towards the room and it will be pointing towards multiple people, and it should be able to capture everything and gaming, like a car game and everything, whatever people have done with the, like point cloud sensor, which is used for interacting with people, and also, like make a deep dive research on how do I connect it with PS5 and use it.Also include like what are the things I have missed out and what people are doing in the internet and how they are using it more productively and how efficiently these sensors can be used. Make a deep dive research on it.

## Follow-up request: Kinect v1 and PC games

$deep-research @Web search Do both deep research and web search for the Kinect v1, because I have Kinect v1. I want how people are using it for games and what games they are using with PC, not with Xbox or PS4. Right now we are just trying only for PC, and what are the games they have used and what are the GitHub links and anything what they have implemented. So do a deep down research and how they have implemented. So we don't want to reinvent the wheel. Everything already implemented, we just want to reuse and things. If it is any Unity engine or something else, just do whatever.

## Follow-up request: fixed Kinect scanning

$deep-research @Web search Now do deep down research and web search on how productively we can use the Kinect for scanning. For example, if I stand in front of the Kinect, I should be able to scan myself, and if I'm showing some product, I should be able to measure the geometry of that product. So complete geometry of whatever the things in front of it, and able to construct the 3D points, and also give me the STL or whatever the file I want. So people would have done it already on the internet, so I'll search all over in the GitHub, or some portals of Reddit or pages, go all over internet and search for things, how people have done it and how people have solved it. I want a proper solution, how people have done it, and we need to do it. So since for me, I'm going to put the sensor in a static way, and I'm going to run. So I want everything to be in that phase, point towards it.

## Current request: compilation and Ubuntu codebase

Now compile everything into a md file don't leave a word. Put everything in a md file as it, split things accordingly. Produce only docs. Then provide the code base for kinect and ubuntu to establish connection and do the work as expected.


---

<a id="appendix-c"></a>
# Appendix C — First-report citation index

- **R1-1** (`turn632532search0`): [https://learn.microsoft.com/en-us/lifecycle/products/azure-kinect-sdk](https://learn.microsoft.com/en-us/lifecycle/products/azure-kinect-sdk)
- **R1-2** (`turn632532search1`): [https://github.com/microsoft/Azure-Kinect-Sensor-SDK](https://github.com/microsoft/Azure-Kinect-Sensor-SDK)
- **R1-3** (`turn632532search2`): [https://learn.microsoft.com/en-us/answers/questions/532418/legality-of-using-kinect-as-motion-capture-hardwar](https://learn.microsoft.com/en-us/answers/questions/532418/legality-of-using-kinect-as-motion-capture-hardwar)
- **R1-4** (`turn897579search0`): [https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/About%20Femto%20Bolt](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/About%20Femto%20Bolt)
- **R1-5** (`turn897579search5`): [https://www.orbbec.com/products/tof-camera/femto-bolt/](https://www.orbbec.com/products/tof-camera/femto-bolt/)
- **R1-6** (`turn897579search2`): [https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Synchronize%20Multiple%20Femto%20Bolt%20Devices](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Synchronize%20Multiple%20Femto%20Bolt%20Devices)
- **R1-7** (`turn980399search5`): [https://pmc.ncbi.nlm.nih.gov/articles/PMC9002889/](https://pmc.ncbi.nlm.nih.gov/articles/PMC9002889/)
- **R1-8** (`turn999613search0`): [https://pmc.ncbi.nlm.nih.gov/articles/PMC5336086/](https://pmc.ncbi.nlm.nih.gov/articles/PMC5336086/)
- **R1-9** (`turn999613search9`): [https://learn.microsoft.com/en-us/previous-versions/windows/kinect/dn772770%28v%3Dieb.10%29](https://learn.microsoft.com/en-us/previous-versions/windows/kinect/dn772770%28v%3Dieb.10%29)
- **R1-10** (`turn632532search9`): [https://www.microsoft.com/en-us/download/details.aspx?id=104015](https://www.microsoft.com/en-us/download/details.aspx?id=104015)
- **R1-11** (`turn401293search1`): [https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Femto%20Bolt%20Hardware%20Specifications](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Femto%20Bolt%20Hardware%20Specifications)
- **R1-12** (`turn999613search7`): [https://pmc.ncbi.nlm.nih.gov/articles/PMC4782741/](https://pmc.ncbi.nlm.nih.gov/articles/PMC4782741/)
- **R1-13** (`turn999613search12`): [https://learn.microsoft.com/en-us/answers/questions/1210718/how-to-record-seated-mode-in-kinect-v1](https://learn.microsoft.com/en-us/answers/questions/1210718/how-to-record-seated-mode-in-kinect-v1)
- **R1-14** (`turn999613search42`): [https://download.microsoft.com/download/6/7/6/676611b4-1982-47a4-a42e-4cf84e1095a8/kinecthig.2.0.pdf](https://download.microsoft.com/download/6/7/6/676611b4-1982-47a4-a42e-4cf84e1095a8/kinecthig.2.0.pdf)
- **R1-15** (`turn326238search1`): [https://github.com/OpenKinect/libfreenect2](https://github.com/OpenKinect/libfreenect2)
- **R1-16** (`turn999613search8`): [https://pmc.ncbi.nlm.nih.gov/articles/PMC9879399/](https://pmc.ncbi.nlm.nih.gov/articles/PMC9879399/)
- **R1-17** (`turn980399search2`): [https://github.com/microsoft/Azure-Kinect-Sensor-SDK/blob/develop/kinect-qa.md?plain=1](https://github.com/microsoft/Azure-Kinect-Sensor-SDK/blob/develop/kinect-qa.md?plain=1)
- **R1-18** (`turn401293search3`): [https://www.orbbec.com/products/tof-camera/femto-bolt/](https://www.orbbec.com/products/tof-camera/femto-bolt/)
- **R1-19** (`turn350229search0`): [https://www.orbbec.com/products/stereo-vision-camera/gemini-335/](https://www.orbbec.com/products/stereo-vision-camera/gemini-335/)
- **R1-20** (`turn350229search1`): [https://store.orbbec.com/products/gemini-335](https://store.orbbec.com/products/gemini-335)
- **R1-21** (`turn401293search11`): [https://www.realsenseai.com/products/450-series/](https://www.realsenseai.com/products/450-series/)
- **R1-22** (`turn897579search18`): [https://dev.realsenseai.com/sdk-2-0-code-samples-wrappers-and-languages/openni/](https://dev.realsenseai.com/sdk-2-0-code-samples-wrappers-and-languages/openni/)
- **R1-23** (`turn350229search4`): [https://www.realsenseai.com/products/d555-poe/](https://www.realsenseai.com/products/d555-poe/)
- **R1-24** (`turn350229search8`): [https://realsenseai.com/wp-content/uploads/2025/08/D555-Datasheet-v1.1.pdf](https://realsenseai.com/wp-content/uploads/2025/08/D555-Datasheet-v1.1.pdf)
- **R1-25** (`turn350229search2`): [https://shop.luxonis.com/products/oak-d-pro?Central+RGB+Camera=OV9782](https://shop.luxonis.com/products/oak-d-pro?Central+RGB+Camera=OV9782)
- **R1-26** (`turn350229search3`): [https://checkout.luxonis.com/products/oak-d-pro](https://checkout.luxonis.com/products/oak-d-pro)
- **R1-27** (`turn897579search25`): [https://www.orbbec.com/wp-content/uploads/2023/08/ORBBEC_Datasheet_Femto-Bolt-2.pdf](https://www.orbbec.com/wp-content/uploads/2023/08/ORBBEC_Datasheet_Femto-Bolt-2.pdf)
- **R1-28** (`turn980399search3`): [https://github.com/microsoft/Azure-Kinect-Sensor-SDK/issues/1168](https://github.com/microsoft/Azure-Kinect-Sensor-SDK/issues/1168)
- **R1-29** (`turn980399search10`): [https://learn.microsoft.com/en-us/answers/questions/1336175/what-is-the-highest-accuracy-range-of-the-kinect-w](https://learn.microsoft.com/en-us/answers/questions/1336175/what-is-the-highest-accuracy-range-of-the-kinect-w)
- **R1-30** (`turn980399search11`): [https://learn.microsoft.com/en-gb/answers/questions/231523/azure-kinect-point-cloud](https://learn.microsoft.com/en-gb/answers/questions/231523/azure-kinect-point-cloud)
- **R1-31** (`turn501679search7`): [https://pmc.ncbi.nlm.nih.gov/articles/PMC4327103/](https://pmc.ncbi.nlm.nih.gov/articles/PMC4327103/)
- **R1-32** (`turn980399search7`): [https://pmc.ncbi.nlm.nih.gov/articles/PMC10551660/](https://pmc.ncbi.nlm.nih.gov/articles/PMC10551660/)
- **R1-33** (`turn897579search9`): [https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Record%20Multi-Device%20Synchronized%20Data%20with%20Femto%20Bolt%20Recorder](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Record%20Multi-Device%20Synchronized%20Data%20with%20Femto%20Bolt%20Recorder)
- **R1-34** (`turn999613search19`): [https://www.mdpi.com/1424-8220/15/11/27569.](https://www.mdpi.com/1424-8220/15/11/27569.)
- **R1-35** (`turn401293search30`): [https://www.realsenseai.com/wp-content/uploads/2024/10/Intel-RealSense-D400-Series-Datasheet-October-2024.pdf](https://www.realsenseai.com/wp-content/uploads/2024/10/Intel-RealSense-D400-Series-Datasheet-October-2024.pdf)
- **R1-36** (`turn169073search1`): [https://github.com/microsoft/Azure-Kinect-Sensor-SDK/issues/1043](https://github.com/microsoft/Azure-Kinect-Sensor-SDK/issues/1043)
- **R1-37** (`turn169073search7`): [https://github.com/microsoft/Azure-Kinect-Sensor-SDK/issues/816](https://github.com/microsoft/Azure-Kinect-Sensor-SDK/issues/816)
- **R1-38** (`turn445381search18`): [https://news.xbox.com/en-us/2010/10/19/announcing-the-kinect-launch-portfolio/](https://news.xbox.com/en-us/2010/10/19/announcing-the-kinect-launch-portfolio/)
- **R1-39** (`turn445381search19`): [https://news.xbox.com/en-us/2010/11/05/demo-kinect-joyride/?ver=3.7.1](https://news.xbox.com/en-us/2010/11/05/demo-kinect-joyride/?ver=3.7.1)
- **R1-40** (`turn445381search24`): [https://news.xbox.com/en-us/2011/03/15/demo-dance-central/?ver=3.7.1](https://news.xbox.com/en-us/2011/03/15/demo-dance-central/?ver=3.7.1)
- **R1-41** (`turn445381search0`): [https://www.xbox.com/en-in/games/store/kinect-sports-rivals/brhsml8030zn](https://www.xbox.com/en-in/games/store/kinect-sports-rivals/brhsml8030zn)
- **R1-42** (`turn445381search36`): [https://news.xbox.com/en-us/2011/10/03/demo-forza-motorsport-4/?ver=3.7.1](https://news.xbox.com/en-us/2011/10/03/demo-forza-motorsport-4/?ver=3.7.1)
- **R1-43** (`turn445381search5`): [https://news.xbox.com/en-us/2014/06/10/events-dance-central-e3/](https://news.xbox.com/en-us/2014/06/10/events-dance-central-e3/)
- **R1-44** (`turn445381search22`): [https://news.xbox.com/en-us/2010/07/20/announcing-kinect-pricing-xbox-360-4-gb-console-and-holiday-bundle/](https://news.xbox.com/en-us/2010/07/20/announcing-kinect-pricing-xbox-360-4-gb-console-and-holiday-bundle/)
- **R1-45** (`turn445381search49`): [https://nxeassets.xbox.com/shaxam/0201/c3/e1/c3e1b51a-8c8e-4efb-ad5d-ad3f6e9fe5eb.PDF?v=1](https://nxeassets.xbox.com/shaxam/0201/c3/e1/c3e1b51a-8c8e-4efb-ad5d-ad3f6e9fe5eb.PDF?v=1)
- **R1-46** (`turn445381search40`): [https://news.xbox.com/en-us/2012/03/05/a-preview-of-xbox-360-kinect-arcade-and-windows-phone-games/](https://news.xbox.com/en-us/2012/03/05/a-preview-of-xbox-360-kinect-arcade-and-windows-phone-games/)
- **R1-47** (`turn475468search0`): [https://www.microsoft.com/en-us/research/project/roomalive/](https://www.microsoft.com/en-us/research/project/roomalive/)
- **R1-48** (`turn475468search2`): [https://github.com/microsoft/RoomAliveToolkit](https://github.com/microsoft/RoomAliveToolkit)
- **R1-49** (`turn326238search4`): [https://github.com/rfilkov/AzureKinectUnityFree](https://github.com/rfilkov/AzureKinectUnityFree)
- **R1-50** (`turn326238search8`): [https://github.com/widVE/KinectCloud](https://github.com/widVE/KinectCloud)
- **R1-51** (`turn475468search6`): [https://www.microsoft.com/en-us/research/video/using-depth-camera-touch-sensor-2/](https://www.microsoft.com/en-us/research/video/using-depth-camera-touch-sensor-2/)
- **R1-52** (`turn475468search4`): [https://www.microsoft.com/en-us/research/publication/miragetable-freehand-interaction-projected-augmented-reality-tabletop/](https://www.microsoft.com/en-us/research/publication/miragetable-freehand-interaction-projected-augmented-reality-tabletop/)
- **R1-53** (`turn475468search5`): [https://www.microsoft.com/en-us/research/project/holodesk-direct-3d-interactions-with-a-situated-see-through-display/](https://www.microsoft.com/en-us/research/project/holodesk-direct-3d-interactions-with-a-situated-see-through-display/)
- **R1-54** (`turn475468search1`): [https://www.microsoft.com/en-us/research/project/roomalive-toolkit/](https://www.microsoft.com/en-us/research/project/roomalive-toolkit/)
- **R1-55** (`turn501679search9`): [https://ieeexplore.ieee.org/abstract/document/11701707/](https://ieeexplore.ieee.org/abstract/document/11701707/)
- **R1-56** (`turn501679search6`): [https://pmc.ncbi.nlm.nih.gov/articles/PMC10551660/](https://pmc.ncbi.nlm.nih.gov/articles/PMC10551660/)
- **R1-57** (`turn501679search8`): [https://pmc.ncbi.nlm.nih.gov/articles/PMC4076760/](https://pmc.ncbi.nlm.nih.gov/articles/PMC4076760/)
- **R1-58** (`turn501679search0`): [https://pubmed.ncbi.nlm.nih.gov/27563384/](https://pubmed.ncbi.nlm.nih.gov/27563384/)
- **R1-59** (`turn501679search1`): [https://pubmed.ncbi.nlm.nih.gov/40567995/](https://pubmed.ncbi.nlm.nih.gov/40567995/)
- **R1-60** (`turn501679search2`): [https://pubmed.ncbi.nlm.nih.gov/33902646/](https://pubmed.ncbi.nlm.nih.gov/33902646/)
- **R1-61** (`turn501679search3`): [https://pubmed.ncbi.nlm.nih.gov/28330455/](https://pubmed.ncbi.nlm.nih.gov/28330455/)
- **R1-62** (`turn501679search5`): [https://pmc.ncbi.nlm.nih.gov/articles/PMC7537442/](https://pmc.ncbi.nlm.nih.gov/articles/PMC7537442/)
- **R1-63** (`turn261907search5`): [https://www.playstation.com/en-in/support/hardware/second-controller-assistance/](https://www.playstation.com/en-in/support/hardware/second-controller-assistance/)
- **R1-64** (`turn475468search3`): [https://www.microsoft.com/en-us/research/project/room2room-life-size-telepresence-projected-augmented-reality-environment/](https://www.microsoft.com/en-us/research/project/room2room-life-size-telepresence-projected-augmented-reality-environment/)
- **R1-65** (`turn501679academia10`): [https://arxiv.org/abs/2604.03730](https://arxiv.org/abs/2604.03730)
- **R1-66** (`turn261907search0`): [https://www.playstation.com/en-ca/support/hardware/ps5-hd-camera-support/](https://www.playstation.com/en-ca/support/hardware/ps5-hd-camera-support/)
- **R1-67** (`turn261907search1`): [https://www.playstation.com/en-ae/support/hardware/ps5-usb-ports-guide/](https://www.playstation.com/en-ae/support/hardware/ps5-usb-ports-guide/)
- **R1-68** (`turn261907search8`): [https://www.playstation.com/en-in/accessories/hd-camera/](https://www.playstation.com/en-in/accessories/hd-camera/)
- **R1-69** (`turn261907search7`): [https://www.playstation.com/en-gb/support/games/ps5-backward-compatibility-games/](https://www.playstation.com/en-gb/support/games/ps5-backward-compatibility-games/)
- **R1-70** (`turn326238search2`): [https://github.com/microsoft/Azure-Kinect-Samples/blob/master/body-tracking-samples/sample_unity_bodytracking/README.md](https://github.com/microsoft/Azure-Kinect-Samples/blob/master/body-tracking-samples/sample_unity_bodytracking/README.md)
- **R1-71** (`turn326238search3`): [https://github.com/microsoft/azure-kinect-samples](https://github.com/microsoft/azure-kinect-samples)
- **R1-72** (`turn261907search3`): [https://www.playstation.com/en-us/remote-play/](https://www.playstation.com/en-us/remote-play/)
- **R1-73** (`turn261907search4`): [https://www.playstation.com/en-ph/support/games/playstation-remote-play-on-pc-and-mac/](https://www.playstation.com/en-ph/support/games/playstation-remote-play-on-pc-and-mac/)
- **R1-74** (`turn672751search4`): [https://github.com/nefarius/vigembus](https://github.com/nefarius/vigembus)
- **R1-75** (`turn672751search5`): [https://github.com/nefarius/ViGEmBus/releases](https://github.com/nefarius/ViGEmBus/releases)
- **R1-76** (`turn672751search0`): [https://github.com/chiaki-ng/chiaki-ng?pubDate=20260509](https://github.com/chiaki-ng/chiaki-ng?pubDate=20260509)
- **R1-77** (`turn672751search2`): [https://github.com/chiaki-ng/chiaki-ng/blob/main/gui/io.github.streetpea.Chiaki4deck.appdata.xml](https://github.com/chiaki-ng/chiaki-ng/blob/main/gui/io.github.streetpea.Chiaki4deck.appdata.xml)
- **R1-78** (`turn672751search3`): [https://github.com/chiaki-ng/chiaki-ng/blob/main/CONTRIBUTOR_GUIDE.md](https://github.com/chiaki-ng/chiaki-ng/blob/main/CONTRIBUTOR_GUIDE.md)
- **R1-79** (`turn169073search2`): [https://microsoft.github.io/Azure-Kinect-Sensor-SDK/master/namespace_microsoft_1_1_azure_1_1_kinect_1_1_sensor_abcc6077f50ba0a9f28733212991e7aa0.html](https://microsoft.github.io/Azure-Kinect-Sensor-SDK/master/namespace_microsoft_1_1_azure_1_1_kinect_1_1_sensor_abcc6077f50ba0a9f28733212991e7aa0.html)
- **R1-80** (`turn326238search0`): [https://github.com/OpenKinect/libfreenect](https://github.com/OpenKinect/libfreenect)
- **R1-81** (`turn401293search12`): [https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Orbbec%20SDK%20and%20Orbbec%20SDK%20K4A%20Wrapper%20%28Femto%20Bolt%29](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Orbbec%20SDK%20and%20Orbbec%20SDK%20K4A%20Wrapper%20%28Femto%20Bolt%29)
- **R1-82** (`turn475468search9`): [https://github.com/genekogan/kinectprojectortoolkit](https://github.com/genekogan/kinectprojectortoolkit)
- **R1-83** (`turn326238search7`): [https://github.com/benja-opazo/home-assistant-hand-recognition](https://github.com/benja-opazo/home-assistant-hand-recognition)
- **R1-84** (`turn169073reddit42`): [https://www.reddit.com/r/kinect/comments/1wrosag/just_discovered_secret_features_on_the_azure/](https://www.reddit.com/r/kinect/comments/1wrosag/just_discovered_secret_features_on_the_azure/)
- **R1-85** (`turn125361search0`): [https://store.orbbec.com/products/femto-bolt](https://store.orbbec.com/products/femto-bolt)
- **R1-86** (`turn125361search1`): [https://www.realsenseai.com/products/450-series/](https://www.realsenseai.com/products/450-series/)
- **R1-87** (`turn350229search5`): [https://www.realsenseai.com/compare-all-cameras/](https://www.realsenseai.com/compare-all-cameras/)
- **R1-88** (`turn125361search5`): [https://www.ebay.com/sch/i.html?_nkw=microsoft+kinect+sensor+v2&_sop=12](https://www.ebay.com/sch/i.html?_nkw=microsoft+kinect+sensor+v2&_sop=12)
- **R1-89** (`turn125361search3`): [https://www.ebay.com/sch/i.html?_nkw=azure+kinect&_sop=12](https://www.ebay.com/sch/i.html?_nkw=azure+kinect&_sop=12)
- **R1-90** (`turn897579search7`): [https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Femto%20Bolt%203D%20Camera%20SDK%20System%20Requirements](https://doc.orbbec.com/documentation/Orbbec%20Femto%20Bolt%20Documentation/Femto%20Bolt%203D%20Camera%20SDK%20System%20Requirements)
- **R1-91** (`turn501679academia11`): [https://arxiv.org/abs/2608.11645](https://arxiv.org/abs/2608.11645)


---

<a id="ubuntu-overview"></a>
# B. Delivered Ubuntu codebase overview

# Kinect v1 Ubuntu Scanner

A local, geometry-first reference implementation for **the original Kinect v1 / Xbox 360 sensor**, a **fixed camera**, and either a stationary subject or a rotating subject.

**Validation status:** the delivered code passed **38 automated tests** and the synthetic end-to-end workflow in the execution environment. **One Open3D test was skipped because Open3D was not installed. No physical Kinect was available, and the Ubuntu installer, USB acquisition, graphical preview, real-object registration, and TSDF reconstruction were not exercised here.** Read [the validation report](docs/VALIDATION.md) before treating this as a deployed system.

This is implementation code, not a claim of tested plug-and-play hardware support. Multi-view reconstruction is capture-then-process, not a live fusion interface.

## What is implemented

| Capability | Command / implementation |
|---|---|
| Inspect dependencies and USB enumeration | `kinectscan doctor` |
| Connect to Kinect v1 and obtain device-specific factory projection parameters | `kinectscan probe` |
| Live depth preview | `kinectscan preview` |
| Empty-scene background capture | `kinectscan background` |
| Stationary-view point cloud, observed-surface mesh, measurements | `kinectscan snapshot` |
| Distance between two visible pixels | `kinectscan measure` |
| Fixed-camera recording of a slowly rotating subject | `kinectscan record` |
| Fit a turntable axis from an off-axis target's measured 3D orbit | `kinectscan axis-fit` |
| Manually indexed, stop-and-hold turntable recording | `kinectscan turntable` |
| Known-pose multi-view point-cloud fusion without Open3D | `kinectscan fuse-known` |
| Open3D registration and TSDF reconstruction | `kinectscan reconstruct` |
| Point-cloud/mesh viewing and mesh-format conversion | `kinectscan view`, `convert` |
| Topology checks | `kinectscan mesh-check` |
| Reproducible hardware-free example | `kinectscan demo` |

The code reuses **libfreenect** for acquisition and **Open3D** for ICP, pose-graph optimization, and TSDF reconstruction. NumPy/SciPy handle masks, coordinate transforms, lightweight geometry, and tests. [Sources and API references](docs/SOURCES.md).

## Scope boundaries

A stationary subject produces **only its visible surfaces**. A rotating subject exposes additional views; surfaces never observed are not manufactured as measurement data. An STL may be open and not printable. No automatic hole completion, textured mesh, STEP/BREP conversion, non-rigid human reconstruction, face recognition, skeleton-game integration, or motor controller is included.

`record --stationary` is valid only when **both** camera and subject stay still. The static reconstruction mode rejects sessions not explicitly marked stationary. The turntable mode assumes a measured axis and accurately indexed angles; it does not claim to measure those angles with an encoder.

All processing stays on your PC. No account, remote service, or cloud upload is used.

## Reference environment

Use **Ubuntu 22.04 or 24.04, x86-64, Python 3.10–3.12** for the full reference stack. These are conservative target environments, not a claim that a particular Ubuntu release is the latest. `requirements-ubuntu.txt` fixes the numerical, preview, reconstruction, and testing packages. The dependency-light core was tested here under a different environment recorded in `docs/VALIDATION.md`.

You need the **Kinect v1 external power/USB adapter**. A USB cable without the sensor's required external power is not enough. Do not install libfreenect2 or a Microsoft Windows SDK for this Ubuntu workflow.

## Install and connect

Read the script before running it. It changes apt packages, a Kinect-specific udev file, and your `plugdev` group membership. It does not disable Secure Boot, replace system Python, or make all USB devices world-writable.

```bash
cd kinect-v1-ubuntu-scanner
bash scripts/install_ubuntu.sh

# Log out and back in after group changes; reconnect the powered Kinect.
source .venv/bin/activate
kinectscan doctor
kinectscan probe --out intrinsics.json
kinectscan preview --z-min 0.7 --z-max 3.5
```

The probe does not invent a focal length. It derives the library's device-specific pinhole parameters from `freenect_sync_camera_to_world`. When that function is unavailable, it stops and asks for a separately calibrated `--intrinsics` file or an appropriate official libfreenect build.

**Factory projection is not independent metrology calibration.** Check physical dimensions against reference objects before relying on measurements.

## First product scan

Keep the sensor and background fixed. Remove the product for the background recording, then place it back. Adjust the example ROI to your scene.

```bash
mkdir -p runs
kinectscan background --out runs/empty.npz --samples 30

kinectscan snapshot \
  --background runs/empty.npz \
  --roi 100 40 540 450 \
  --z-min 0.8 --z-max 1.8 \
  --out runs/product_front
```

Outputs include PLY/PCD/XYZ point clouds, PLY/OBJ/STL observed-surface meshes, a saved depth frame, and a JSON measurement report. **PLY/PCD/XYZ/OBJ coordinates are meters; STL coordinates are millimeters**, accompanied by a units sidecar.

For complete dimensions, capture additional orientations. Do not interpret a front-surface bounding box as a complete object envelope.

## Rotating-subject scan

```bash
kinectscan record \
  --background runs/empty.npz \
  --roi 100 40 540 450 \
  --z-min 0.8 --z-max 2.0 \
  --seconds 60 --fps 5 --delay 5 \
  --out runs/product_rotation

kinectscan reconstruct \
  --session runs/product_rotation \
  --mode auto \
  --voxel-m 0.006 \
  --out runs/product_reconstruction
```

Rotate slowly while preserving shape. Do not move the sensor, table, or background. The automatic rigid-registration route is **experimental until tested on your scene**. It is not a non-rigid body scanner and cannot guarantee alignment for smooth, symmetric, or deforming subjects.

See [the complete guide](docs/INSTALL_AND_USAGE.md) for the calibrated turntable route, self-scanning precautions, transformations, outputs, and troubleshooting.

## Test without a Kinect

```bash
python -m pytest -q
kinectscan demo --out runs/synthetic_session
kinectscan fuse-known \
  --session runs/synthetic_session \
  --out runs/synthetic_cloud

# Requires Open3D:
kinectscan reconstruct \
  --session runs/synthetic_session \
  --mode known \
  --out runs/synthetic_mesh
```

The included `examples/synthetic_session` and its preview exports are **generated analytical test data, not real Kinect captures**.

## Code map

| File | Responsibility |
|---|---|
| `src/kinectscan/capture.py` | libfreenect ctypes binding, copied buffers, killable worker, read timeout |
| `src/kinectscan/geometry.py` | Intrinsics, invalid-depth handling, rectification, masks, rays, mesh, transformations, axis fitting |
| `src/kinectscan/storage.py` | Safe local records, manifests, PLY/PCD/XYZ/OBJ/STL writers, explicit units |
| `src/kinectscan/reconstruct.py` | Open3D ICP/pose graph/TSDF and known-pose point fusion |
| `src/kinectscan/synthetic.py` | Analytical raycasts and known-pose synthetic sessions |
| `src/kinectscan/cli.py` | All command-line workflows |
| `tests/` | Geometry, storage, CLI, mocked C binding, and optional Open3D tests |
| `config/99-kinectscan.rules` | Restricted Kinect v1 device access |
| `scripts/install_ubuntu.sh` | Reference Ubuntu installer |
| `scripts/smoke_test.sh` | Hardware-free workflow |

## License

The new glue/application code is MIT-licensed; see `LICENSE`. Third-party libraries and the independently linked repositories retain their own licenses. This package does not redistribute Microsoft SDKs, proprietary scanner applications, firmware, or third-party game assets.


---

<a id="ubuntu-guide"></a>
# C. Ubuntu installation and scanning guide

# Kinect v1 + Ubuntu: installation, fixed scanning, measurement, and export

**Prepared:** November 17, 2026  
**Hardware:** original Kinect v1 / Xbox 360; not Kinect v2, Azure Kinect, or Orbbec  
**Code package:** `kinect-v1-ubuntu-scanner`, version 0.1.0

## 1. Status and interpretation

This guide accompanies an implemented Python command-line application, not pseudocode. Multi-view reconstruction is a **capture-then-process workflow**, not a live fusion interface. Its software-only validation is described in the validation report. **Physical USB acquisition and Open3D registration/fusion were not tested in the authoring environment.** Verify the stages below on your Ubuntu computer in order.

The earlier research archive is preserved separately. Windows applications such as ReconstructMe, RecFusion, and FaceFusion are historical research references; they are **not dependencies** of this Ubuntu implementation. Nor does this package port the earlier Windows-only games or skeleton SDKs to Linux.

The intended system is:

```text
Externally powered Kinect v1, physically fixed
        |
        +-- libfreenect: 640 x 480 metric IR-frame depth
        |
        +-- calibration + valid-depth filtering + foreground isolation
        |
        +-- snapshot:
        |      observed point cloud -> visible geometry / measurements
        |      observed grid triangles -> open surface mesh
        |
        +-- rotating subject:
               saved depth frames + relative poses
                  -> registration / known turntable poses
                  -> Open3D TSDF
                  -> mesh + point cloud + measurement report
```

A complete-looking model is not proof of complete measurement. Back faces, the underside, deep recesses, and occluded limbs require additional viewpoints. Mesh repair belongs in a separate, clearly identified printing workflow.

## 2. System requirements and version strategy

The reference installation targets Ubuntu 22.04/24.04 on x86-64 with Python 3.10–3.12. It deliberately uses a fixed Open3D 0.19.0 API and dependency set rather than automatically switching to whichever package is newest. Open3D's published installation matrix includes these Python versions and Linux support. [S4]

A reasonable starting machine has a multi-core CPU and enough RAM for the number of recorded frames; 8–16 GB is a practical planning suggestion, not a measured minimum for this package. CPU reconstruction is used; CUDA is not required by this implementation. A desktop session is needed for the preview/view commands, but capture, conversion, point fusion, and reconstruction do not depend on a graphical window.

For Ubuntu releases using a different default Python, create a separate compatible interpreter environment. **Do not replace the operating system's Python.** The installer deliberately rejects Python versions outside its full-stack reference range. An already installed compatible interpreter can be selected with `PYTHON_BIN`.

The Ubuntu repositories publish `libfreenect-dev` and `libfreenect-bin`; the package version may be older than upstream. [S2] The application uses libfreenect, not libfreenect2. [S1]

## 3. Hardware connection

Connect the Kinect to its original-compatible **external power and USB adapter**, then to the computer. Prefer a direct USB port for the first test. Do not begin with a long extension, an unpowered hub, a virtual machine, or a USB-over-network setup.

Keep the camera mechanically stationary during a session. Do not use its tilt motor to sweep while calling the scan “fixed.” Any mount/pitch change invalidates the captured background and the turntable-axis calibration.

The earlier room discussion contains an unresolved mounting ambiguity: “6–7 feet above the TV” is not necessarily “6–7 feet above the floor.” Record the actual camera height, pitch, and subject distance. The software uses camera-relative coordinates unless you supply a separately calibrated frame transformation.

## 4. Installation

Unpack the ZIP, open a terminal in the codebase directory, and inspect the installer:

```bash
cd kinect-v1-ubuntu-scanner
less scripts/install_ubuntu.sh
bash scripts/install_ubuntu.sh
```

The installer:

- Installs the Ubuntu libfreenect and supporting packages.
- Adds `config/99-kinectscan.rules` and `plugdev` access for the listed Kinect USB functions.
- Creates `.venv`, installs the fixed Python requirements, installs the local package, and records `installed-versions.txt`.

The rule intentionally uses group access and desktop `uaccess`, rather than broad access to arbitrary USB devices. The IDs are cross-checked against the upstream Kinect udev rules. [S3]

Log out and back in after group membership changes. Unplug/replug the powered Kinect. Activate the environment:

```bash
source .venv/bin/activate
kinectscan doctor
```

Do not run the scanner itself as root. `sudo` is used by the installer only for system package and device-permission changes.

### Manual alternative

For a compatible Ubuntu/Python environment:

```bash
# Select the GLib package name for the reference Ubuntu release.
. /etc/os-release
case "$VERSION_ID" in
  22.04) GLIB_PACKAGE=libglib2.0-0 ;;
  24.04) GLIB_PACKAGE=libglib2.0-0t64 ;;
  *) echo "Review package names for this release."; exit 1 ;;
esac
sudo apt-get update
sudo apt-get install -y \
  python3-venv python3-dev \
  libfreenect-dev libfreenect-bin \
  libusb-1.0-0 usbutils libgl1 "$GLIB_PACKAGE"

# Inspect the rules before installing them.
sudo install -m 0644 config/99-kinectscan.rules \
  /etc/udev/rules.d/99-kinectscan.rules
sudo usermod -aG plugdev "$USER"
sudo udevadm control --reload-rules

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install --only-binary=:all: -r requirements-ubuntu.txt
python -m pip install --no-deps -e .
```

The GLib package name differs between Ubuntu 22.04 and 24.04; the branch above follows the Ubuntu package records. [S9] [S10]

The manual path assumes the `universe` repository and `plugdev` group already exist; the script handles those checks. After permission changes, log out/in and reconnect the sensor.

Do not install a random `freenect` package from PyPI. The code calls the system C library via `ctypes`; it does not require the historical Cython wrapper.

## 5. First connection and calibration record

```bash
kinectscan probe --out intrinsics.json
```

Expected results are a nonzero valid-depth fraction and a device-specific intrinsics record. No fixed focal-length guess is silently substituted.

The acquisition mode is **`FREENECT_DEPTH_MM`**, whose values are millimeters in the IR/depth image frame, not RGB-aligned depth. This distinction is explicit in libfreenect's API. [S5]

The probe samples `freenect_sync_camera_to_world` to obtain the pinhole ray model corresponding to the device/library. The driver implementation uses the device's zero-plane parameters. [S6] This is a useful factory starting point, **not a complete independent calibration or depth-bias correction**.

### Separately calibrated intrinsics

A user-supplied file has this schema:

```json
{
  "width": 640,
  "height": 480,
  "fx": 580.0,
  "fy": 580.0,
  "cx": 320.0,
  "cy": 240.0,
  "source": "EXAMPLE ONLY - replace with your calibrated IR camera parameters",
  "distortion": [],
  "depth_format": "FREENECT_DEPTH_MM"
}
```

**The numbers above are schema examples, not recommended calibration values.** Normally, use the real `probe` output. To override it:

```bash
kinectscan probe \
  --intrinsics my_calibrated_ir_intrinsics.json \
  --out checked_intrinsics.json
```

Distortion coefficients, when supplied, use OpenCV's `[k1, k2, p1, p2, k3, ...]` convention. The application supports 4, 5, or 8 coefficients and rectifies with nearest-neighbor sampling. Provide coefficients for the **actual IR depth coordinate frame**, not the RGB camera.

No independent checkerboard-calibration capture tool is included. Measuring known objects is necessary even with factory intrinsics.

## 6. Preview and foreground selection

```bash
kinectscan preview --z-min 0.7 --z-max 3.5
```

Press `Q` or Escape to exit. Black pixels are missing or excluded depth.

ROI syntax is `x0 y0 x1 y1`; the end coordinates are exclusive. A 3D crop is `xmin xmax ymin ymax zmin zmax`, in meters:

```bash
kinectscan preview \
  --roi 100 40 540 450 \
  --box -0.4 0.4 -0.4 0.2 0.8 1.8 \
  --z-min 0.8 --z-max 1.8
```

These values are examples. Tune them while looking at your actual depth preview. With a high-mounted/tilted camera, camera `Y` is not necessarily vertical in the room.

### Empty-scene background

Keep the rotating platform and stationary surroundings in place, but remove the product or person:

```bash
mkdir -p runs
kinectscan background \
  --out runs/empty.npz \
  --samples 30 \
  --delay 3
```

The background is a robust temporal median; invalid measurements remain invalid. A candidate foreground point must be closer than valid background by the configured margin, 25 mm by default.

```bash
kinectscan preview \
  --background runs/empty.npz \
  --background-margin-mm 25 \
  --roi 100 40 540 450 \
  --z-min 0.8 --z-max 1.8
```

Pixels with no valid background are rejected rather than assumed to be foreground. This can remove genuine subject pixels where the background was too far away or reflective. Improve the background or use carefully bounded ROI/3D cropping instead.

The optional `--largest-component` retains one connected silhouette. It can remove disconnected limbs or multiple products; leave it off for a person until you inspect the mask.

**This is not semantic object segmentation.** Hands holding a product may be included. Use a stand, remove the hands before capture, and inspect the support-plane boundary.

## 7. Stationary snapshot: immediate geometry and measurements

```bash
kinectscan snapshot \
  --background runs/empty.npz \
  --roi 100 40 540 450 \
  --z-min 0.8 --z-max 1.8 \
  --samples 15 \
  --out runs/product_front
```

The subject must stay still during the median capture. With temporal rejection:

```bash
kinectscan snapshot \
  --roi 100 40 540 450 \
  --samples 20 \
  --max-std-mm 10 \
  --out runs/stable_front
```

The threshold is a tunable capture criterion, not a claim of 10 mm accuracy.

### Files produced

| File | Meaning |
|---|---|
| `frame.npz` | Processed metric depth, intrinsics, timestamps, and pre-segmentation captured depth |
| `capture_intrinsics.json` | Original capture calibration metadata |
| `observed_points.ply` | Visible 3D points, meters |
| `observed_points.pcd` | Same point geometry, meters |
| `observed_points.xyz` | Same points as text, meters |
| `observed_mesh.ply` | Grid-triangulated observed surface, meters |
| `observed_mesh.obj` | Geometry-only mesh, meters |
| `observed_mesh.stl` | Geometry-only mesh, millimeter coordinates |
| `observed_mesh.stl.units.json` | Explicit companion unit information |
| `measurements.json` | AABB/PCA/percentile extents with limitations |

The mesh connects neighboring valid depth pixels only. It refuses triangles whose edges exceed `--max-edge-m`; the default is 0.04 m. It does not cap silhouettes, bridge missing samples, or invent the back surface. The output can therefore be open. Lowering `--stride` from 2 to 1 increases sampling density, **not sensor accuracy**.

The bounding box describes the included observations. A front scan of a bottle does not establish its unseen depth. The PCA box is data-oriented; it is not guaranteed to align with the intended product length/width/height. Percentile extents intentionally discard extremes and may understate physical size.

### Point-to-point distance

Select valid pixels from the saved, rectified depth image:

```bash
kinectscan measure \
  --input runs/product_front/frame.npz \
  --p1 250 220 --p2 390 220 \
  --out runs/product_front/distance.json
```

The default uses the exact pixels. `--radius 2` uses a 5×5 patch median while retaining the requested central ray. That assumes a locally uniform surface and should not be used across a depth discontinuity.

The output gives both endpoint coordinates and their Euclidean separation. Missing endpoints generate an error, not a guessed measurement.

## 8. Fixed camera with free rotation: automatic reconstruction

For an irregular rigid product, use a slow continuous rotation and foreground isolation:

```bash
kinectscan record \
  --background runs/empty.npz \
  --roi 100 40 540 450 \
  --z-min 0.8 --z-max 2.0 \
  --seconds 60 --fps 5 --delay 5 \
  --out runs/product_rotation
```

`--fps` is the requested saved-frame sampling rate, not a guarantee of hardware frame rate. Processing, compression, and storage can lower the achieved rate; device and host timestamps are retained.

The record contains:

```text
product_rotation/
  session.json
  frames/
    000000.npz
    000001.npz
    ...
```

The manifest is updated after each complete frame. An interrupted session remains available, marked incomplete.

Reconstruct:

```bash
kinectscan reconstruct \
  --session runs/product_rotation \
  --mode auto \
  --voxel-m 0.006 \
  --out runs/product_reconstruction
```

The implementation reuses Open3D's point-to-plane ICP at progressively finer scales. [S7] Each current cloud is registered into the previous cloud, then composed into the first-view reference frame. Cropping/background isolation happens **before** registration.

Frames are rejected when overlap, residual, or inter-frame motion fail configurable gates. On failure, `registration_failure.json` explains the first rejected frame and the command stops before TSDF fusion. It does not continue silently building a corrupted model.

### Optional full-loop constraint

Only use this after actually returning the subject to its original view:

```bash
kinectscan reconstruct \
  --session runs/product_rotation \
  --mode auto --close-loop \
  --out runs/product_loop_reconstruction
```

The code checks a last-to-first registration and uses an Open3D pose graph. A successful numerical check is not proof that a symmetric object was aligned correctly. Inspect the seam and known dimensions.

### Limits of automatic rotation

Smooth spheres, cylinders, repeated patterns, occlusion, large angle jumps, or a person changing pose can defeat rigid ICP. A low residual can still be the wrong correspondence. This reference implementation does not include robust non-rigid human tracking, semantic body isolation, or a globally guaranteed feature-based registration system.

For repeatable product scanning, prefer a measured turntable axis and controlled positions.

## 9. Indexed turntable workflow

The Kinect remains fixed; the product rotates on a stable platform. **No motor-control hardware is assumed or driven by this code.** Angles are entered through a manual indexed stop-and-hold sequence.

### 9.1 Measure the rotation axis

Place a small matte target away from the rotation axis and capture its center position at six or more angular positions spanning at least 180°, preferably around a full circle. Keep target height fixed.

One practical way to obtain XYZ positions is to make snapshots, locate the target pixel, and use `measure` with the same pixel for both endpoints:

```bash
kinectscan measure \
  --input runs/axis_view_01/frame.npz \
  --p1 300 210 --p2 300 210 \
  --out runs/axis_point_01.json
```

Extract `point1_m` from each result into a CSV:

```csv
x_m,y_m,z_m
0.12,0.10,1.25
0.09,0.10,1.32
...
```

Those rows only illustrate the file layout. Do not use the illustrative coordinates as your calibration.

Fit:

```bash
kinectscan axis-fit \
  --points runs/axis_points.csv \
  --skiprows 1 \
  --input-units m \
  --preferred-axis 0 -1 0 \
  --out runs/axis.json
```

`--preferred-axis` chooses the normal's sign, not an assumed exact physical direction. For a tilted camera, the fitted direction need not equal `[0, -1, 0]`.

The fit reports radius, residual, sample count, and angular coverage. It rejects collinear/short-arc data, coverage below 180°, and residual above the chosen threshold. These checks are not a calibration certificate.

### 9.2 Confirm direction

Positive angles follow the right-hand rule about `axis`. Viewed from the positive end of the axis toward its center, positive rotation is counter-clockwise.

Before a long scan, capture a small positive turn and inspect point alignment. A sign mistake makes the model unwind incorrectly. Camera tilt or a flipped axis can make everyday “clockwise” descriptions ambiguous; use the documented vector convention.

### 9.3 Capture at indexed stops

```bash
kinectscan turntable \
  --axis runs/axis.json \
  --step-deg 10 \
  --samples 15 \
  --settle-sec 0.7 \
  --background runs/empty.npz \
  --roi 100 40 540 450 \
  --z-min 0.8 --z-max 1.8 \
  --out runs/indexed_product
```

The program prompts at 0°, 10°, …, 360°. Set the physical platform to each mark, stop motion, and press Enter. Its timestamps do **not** verify that the platform reached the commanded angle.

### 9.4 Fuse points, then reconstruct the surface

First inspect point alignment without requiring Open3D:

```bash
kinectscan fuse-known \
  --session runs/indexed_product \
  --voxel-m 0.005 \
  --out runs/indexed_cloud
```

Then run TSDF:

```bash
kinectscan reconstruct \
  --session runs/indexed_product \
  --mode known \
  --voxel-m 0.006 \
  --out runs/indexed_mesh
```

Known-pose mode uses the calibrated axis and assumed indexed angles; it does not silently alter them with ICP. This helps diagnose axis, angle, and scale errors separately.

## 10. Why the relative transforms matter

All stored coordinates are in meters with camera axes **X right, Y down, Z forward**. The reconstruction world is the camera coordinate frame when the subject is at its initial orientation.

For an object rotating around center `c` with rotation `R(θ)`:

```text
p_camera(theta) = R(theta) * p_world + c - R(theta) * c

G(theta) = T_camera_from_world
T_world_from_camera = inverse(G(theta))
```

The physical camera does not move, but the **object-relative virtual camera pose changes**. Fusing every rotating frame with the identity transform is incorrect.

The session stores `T_world_from_camera`. Open3D's TSDF integration expects the inverse, `T_camera_from_world`; the code performs that inversion explicitly. [S8]

The `static` mode exists only for genuine stationary-scene averaging:

```bash
kinectscan record \
  --stationary \
  --seconds 5 --fps 5 \
  --roi 100 40 540 450 \
  --out runs/stationary_scene

kinectscan reconstruct \
  --session runs/stationary_scene \
  --mode static \
  --out runs/stationary_mesh
```

Do not apply this mode to a rotating person or product.

## 11. Self-scanning

Begin with a head/shoulders snapshot. Then attempt a slow seated or standing rotation with the camera fixed and the entire included body region moving as rigidly as possible.

Capture the empty background before the person enters. Choose an ROI and depth interval that include the whole desired subject region but exclude as much stationary furniture as possible. Use `record`, not a temporal median over an actively rotating person.

The automatic registration path may be useful for a cooperative bust scan, but **human pose changes violate its rigid-scene model**. It is not guaranteed to produce a faithful full-body model. Top-of-head, under-chin, armpit, between-leg, sole, and back coverage cannot be inferred from a front view.

For self-operation, the recording command has a start delay and fixed duration. Have another person operate the computer during early experiments. Do not use a tabletop product turntable for a person; use a safe human-rated platform or a safe controlled turn. This code does not operate powered motion hardware.

Full-body capture from a high room mount is a different geometry from close-up product measurement. Do not assume one permanent position is optimal for all subjects.

## 12. Export, inspection, and printing

Reconstruction produces `fused_points.*`, `fused_mesh.*`, `measurements.json`, `poses.json`, and `quality.json`.

```bash
kinectscan view --input runs/indexed_mesh/fused_mesh.ply

kinectscan mesh-check \
  --input runs/indexed_mesh/fused_mesh.ply \
  --out runs/indexed_mesh/topology.json
```

The topology command checks watertightness, manifold properties, and orientability. It does not certify completeness, measurement accuracy, or printer suitability.

### Unit-safe conversion

```bash
kinectscan convert \
  --input runs/indexed_mesh/fused_mesh.ply \
  --input-units m \
  --out runs/indexed_mesh/print_model.stl \
  --stl-units mm
```

STL geometry has no standardized embedded unit declaration. The code writes millimeter coordinates by default and supplies a sidecar. Verify a known dimension in the receiving slicer.

PLY/OBJ written by this application use meter coordinates and are geometry-only. A PCD/XYZ point cloud is not a surface mesh. A mesh with no triangles cannot be “converted” into STL by renaming it; the converter rejects such input.

**Not implemented:** texture atlases, textured OBJ/GLB, 3MF packaging, STEP/IGES, parametric feature fitting, automatic watertight repair, or an arbitrary-format exporter. Use an appropriate mesh/CAD tool for those downstream tasks. The earlier research discusses some formats that the delivered application deliberately does not claim to write.

Preserve the measurement copy. Make hole filling, smoothing, capping, or miniature scaling only on a separately named printing copy. Record the operations. Repaired regions are inferred geometry, not additional sensor observations.

## 13. Validation on your actual sensor

Use rigid, matte reference objects of independently known size. Scan five times with the same mount, settings, and range. Record extents and repeatability before any cosmetic repair.

Suggested acceptance worksheet:

| Check | Record |
|---|---|
| Sensor identification | Model/serial if available; adapter; USB port/controller |
| Environment | Ubuntu version; Python and package versions |
| Geometry | Camera height/pitch; target range; target size |
| Projection | Factory or independently calibrated intrinsics |
| Segmentation | ROI/3D bounds/background and rejected regions |
| Repeatability | Five independent scans and dimension spread |
| Bias | Mean dimension minus independent reference |
| Registration | Any rejected frames, seam mismatch, false alignments |
| Export scale | Dimension checked after opening STL in the slicer |
| Coverage | Which faces were actually observed; remaining holes |

Define your acceptable error **before** interpreting the results. A 6 mm TSDF voxel or a 10 mm gate is not a promised measurement accuracy. A high point count is not proof of precision. Do not use this unvalidated reference scanner for safety-critical inspection or medical decisions.

## 14. Troubleshooting

| Symptom | First checks |
|---|---|
| `libfreenect_sync not found` | Install Ubuntu's development/runtime packages; inspect `ldconfig -p`; do not install libfreenect2 |
| Sensor opens only as root | Inspect udev/group membership; log out/in; reconnect; do not use permanent root execution as the fix |
| Only motor function enumerates | Check the correct external adapter, power, USB cable/port, and sensor health |
| USB claim/busy error | Close other Kinect applications; check whether a kernel camera driver has claimed the device |
| Worker timeout after disconnect | Restore connection and rerun; the CLI terminates its acquisition worker instead of waiting indefinitely |
| All-zero depth | Inspect distance, surface, IR environment, power, and hardware health |
| Background removes real subject | Check background validity and margin; recapture or use carefully bounded spatial cropping |
| Floor/table merges into product | Narrow the ROI/3D box; remove the support region before registration |
| Rotating model smears or duplicates | Check background isolation, relative-pose mode, axis position, and angle sign |
| ICP fails | Reduce inter-frame rotation, improve overlap/geometry, avoid deforming subjects, or use calibrated indexed rotation |
| ICP appears good but wrong | Symmetry/planarity can give misleading residuals; inspect landmarks and independent dimensions |
| STL is 1000× too large/small | Agree on units in exporter/importer and read the units sidecar |
| GUI fails on a remote/headless system | Use non-GUI commands; run preview/view on a working local desktop |
| Python/Open3D installation fails | Use the documented Python 3.10–3.12 reference environment; do not replace system Python |

A kernel-driver conflict can require system-specific work. Inspect it before changing anything; this installer does not automatically unload modules or install permanent blacklists. Follow upstream libfreenect troubleshooting where appropriate. [S1]

## 15. Data, privacy, and reproducibility

Frames and geometry remain on disk locally. Body scans and room geometry can still be sensitive even without RGB. Obtain consent, select a private output directory, and delete unneeded recordings.

Use a new output directory for each run. The commands refuse nonempty output directories rather than overwrite earlier scans. Preserve the original frame session, calibration, manifest, package versions, and measurement report alongside any repaired printing asset.

The package includes a synthetic example for debugging. **Do not mix its synthetic intrinsics or geometry with hardware measurements.**

## 16. Command reference

```text
kinectscan doctor
kinectscan probe --out intrinsics.json
kinectscan preview [sensor and segmentation options]
kinectscan background --out empty.npz
kinectscan snapshot --out scan_directory [--input saved_frame.npz]
kinectscan measure --input frame.npz --p1 U V --p2 U V
kinectscan record --out session_directory [--stationary]
kinectscan axis-fit --points orbit.csv --out axis.json
kinectscan turntable --axis axis.json --out session_directory
kinectscan fuse-known --session session_directory --out cloud_directory
kinectscan reconstruct --session session_directory --mode auto|known|static --out mesh_directory
kinectscan view --input geometry.ply
kinectscan convert --input mesh.ply --input-units m --out mesh.stl
kinectscan mesh-check --input mesh.ply
kinectscan demo --out synthetic_session
```

Every command has `--help`. This guide's examples are proposals for a starting workflow; ROI, range, axis, and acceptance thresholds must be adapted to the actual installation.

## Sources for the Ubuntu implementation

[S1]: https://github.com/OpenKinect/libfreenect
[S2]: https://packages.ubuntu.com/source/noble/libfreenect
[S3]: https://github.com/OpenKinect/libfreenect/blob/master/platform/linux/udev/51-kinect.rules
[S4]: https://www.open3d.org/docs/0.19.0/getting_started.html
[S5]: https://sources.debian.org/src/libfreenect/1%3A0.1.2%2Bdfsg-6/include/libfreenect.h/
[S6]: https://sources.debian.org/src/libfreenect/1%3A0.5.3-1/src/registration.c
[S7]: https://www.open3d.org/docs/0.19.0/python_api/open3d.pipelines.registration.registration_icp.html
[S8]: https://www.open3d.org/docs/0.19.0/tutorial/pipelines/rgbd_integration.html
[S9]: https://packages.ubuntu.com/jammy/libglib2.0-0
[S10]: https://packages.ubuntu.com/noble/libglib2.0-0t64

- **[S1]** OpenKinect libfreenect: original-Kinect driver, build instructions, and project limitations.
- **[S2]** Ubuntu 24.04 package records for libfreenect.
- **[S3]** Upstream Kinect USB identifiers and udev rules.
- **[S4]** Open3D 0.19 installation/platform documentation.
- **[S5]** Original libfreenect depth-format API, including metric IR-frame versus registered depth.
- **[S6]** libfreenect factory camera-to-world projection implementation.
- **[S7]** Open3D ICP API.
- **[S8]** Open3D volumetric integration and inverse-pose convention.
- **[S9]** Ubuntu 22.04 GLib runtime package.
- **[S10]** Ubuntu 24.04 GLib runtime package.

The transformation equations, command organization, rejection policies, and test procedures in this guide describe the delivered implementation. They are not manufacturer accuracy guarantees.


---

<a id="ubuntu-validation"></a>
# D. Validation report

# Validation report

**Date:** November 17, 2026  
**Package:** Kinect v1 Ubuntu Scanner 0.1.0

## Result

**38 tests passed; 1 test skipped.**

The skipped test is the Open3D known-pose TSDF test. **Open3D was not installed in the execution environment, and a physical Kinect was not available.**

This report does not claim that the Ubuntu installer, sensor enumeration, real USB streaming, factory calibration query against a real device, graphical preview, or Open3D fusion has been successfully run on target hardware.

## Actual execution environment

| Component | Value |
|---|---|
| OS userspace | Debian GNU/Linux 13 |
| Kernel / architecture | Linux 6.18.57, x86-64 |
| Python | 3.13.5 |
| NumPy | 2.3.5 |
| SciPy | 1.17.0 |
| OpenCV Python | 4.13.0.92 |
| Open3D | Not installed |
| libfreenect_sync | Not installed |
| Physical Kinect | Not available |
| Network from code-execution container | Not available |

This differs from the target **Ubuntu 22.04/24.04 + Python 3.10–3.12** reference environment. It validates the dependency-light code paths, not installation of the pinned full stack.

## Commands executed

```bash
PYTHONPATH=src python3 -m pytest -q
python3 -m compileall -q src
bash -n scripts/install_ubuntu.sh scripts/smoke_test.sh
PYTHONPATH=src python3 -m kinectscan doctor
PYTHONPATH=src python3 -m kinectscan probe --timeout 2
bash scripts/smoke_test.sh /mnt/data/work/smoke
```

The negative probe exited with code **2** and an explicit missing-library message. It was an error-path check, not a successful connection:

```text
ERROR: RuntimeError: libfreenect_sync not found. Install libfreenect-dev and libfreenect-bin, then run ldconfig if built from source.
```

## What the automated tests cover

- Millimeter-to-meter projection, pixel geometry, and invalid-depth handling.
- Intrinsics, image-shape, rigid-transform, ROI, and depth-range validation.
- Temporal median behavior and rejection of missing/unstable samples.
- Signed foreground subtraction without unsigned integer underflow.
- Largest connected silhouette selection.
- Observed-surface triangles, normals, missing samples, and depth discontinuities.
- Turntable pose inversion and full-turn closure on analytic geometry.
- Axis-circle fitting and rejection of collinear data.
- Voxel point averaging and explicit observed-surface extent reporting.
- Frame serialization with pickle disabled.
- PLY, PCD, XYZ, OBJ, and binary STL structure.
- STL millimeter scaling and the units sidecar.
- Refusal to overwrite nonempty directories and rejection of manifest path traversal.
- Synthetic known-pose multi-view point fusion.
- Refusal to use static fusion on a rotating session.
- Offline snapshot/measurement CLI paths and missing-depth errors.
- A **mocked** libfreenect C binding, including copying its reusable memory buffer and deriving intrinsics from a known fake ray model.

## Synthetic end-to-end execution

A deterministic 160×120 analytical camera captured a rotating asymmetric box assembly at known poses. The software generated a session, exported a single observed-surface snapshot, and fused all known-pose views into a point cloud.

The example geometry is intentionally labeled **synthetic** in file names/manifests. It is not a real Kinect capture, not a scanned person or product, and not evidence of sensor accuracy.

## Not exercised here

| Component | Status |
|---|---|
| Ubuntu apt/pip installation | Script inspected and shell syntax checked; not executed on Ubuntu |
| udev / group changes | Not executed |
| Physical power, USB, and sensor streaming | Not tested |
| Factory parameters from a physical Kinect | Not tested |
| Preview GUI / Open3D viewer | Not tested |
| ICP on real rotating products or people | Not tested |
| Open3D pose-graph optimization | Not tested |
| Open3D TSDF and mesh extraction | Optional test skipped |
| `mesh-check` / Open3D-based conversion | Not tested |
| Calibration accuracy, physical repeatability, printability | Not measured |
| Full-body scanning quality | Not validated |

## Required target-machine acceptance sequence

Run the unit suite after installation. With Open3D present, the previously skipped synthetic TSDF test should execute rather than skip. Then run `probe`, inspect a depth preview, capture a stationary reference object, and validate dimensions against an independent measurement.

Only after that should you try known-axis product rotation, automatic registration, and cooperative self-scanning. Preserve diagnostics for failures rather than loosening every threshold until a model appears.

## Additional export and numerical checks

The dependency-light synthetic known-pose fusion produced **27,536 points**. Its
observed axis-aligned extents were approximately **400.94 x 399.96 x 200.88 mm**,
against the synthetic scene's analytic **400 x 400 x 200 mm** envelope. These
numbers validate this generated fixture and its coordinate/export path only;
they are not a Kinect accuracy or reconstruction benchmark.

An independent STL reader (`trimesh`, already present in the authoring
environment) successfully read the exported synthetic observed-surface STL:
**4,240 triangles**, with millimeter-coordinate bounds approximately
`[-195.5, -247.8, 1150.0]` to `[195.5, 149.5, 1200.0]`. This confirms that the
binary export is readable and uses the requested unit scale. It does not prove
watertightness, printability, hidden-surface coverage, or physical accuracy.


---

<a id="ubuntu-references"></a>
# E. Implementation references

# Sources and implementation decisions

The research reports are preserved as historical text in `RESEARCH_ARCHIVE.md` and `research/`. Their claims were not all independently revalidated during the code-generation task. The sources below were consulted for the new Ubuntu implementation.

| Area | Primary source | Decision in this code |
|---|---|---|
| Original Kinect access | [OpenKinect/libfreenect](https://github.com/OpenKinect/libfreenect) | Use libfreenect, not libfreenect2 |
| Ubuntu driver packages | [Ubuntu 24.04 libfreenect](https://packages.ubuntu.com/source/noble/libfreenect) | Prefer the distro package for the baseline; diagnose missing functions explicitly |
| Device access | [Upstream udev identifiers](https://github.com/OpenKinect/libfreenect/blob/master/platform/linux/udev/51-kinect.rules) | Match only original-Kinect USB functions; use restricted group access |
| Metric depth format | [libfreenect API header](https://sources.debian.org/src/libfreenect/1%3A0.1.2%2Bdfsg-6/include/libfreenect.h/) | Request `FREENECT_DEPTH_MM`; do not treat raw 11-bit disparity as millimeters |
| Factory ray model | [libfreenect registration source](https://sources.debian.org/src/libfreenect/1%3A0.5.3-1/src/registration.c) | Query device factory ray mapping rather than copy internet focal lengths |
| C-wrapper API signature | [JavaCPP libfreenect API](https://javadoc.io/static/org.bytedeco/libfreenect/0.5.7-1.5.9/org/bytedeco/libfreenect/global/freenect.html) | Cross-check the exposed `freenect_sync_camera_to_world` signature |
| Acquisition buffer/API | [Upstream Python wrapper source](https://github.com/OpenKinect/libfreenect/blob/master/wrappers/python/freenect.pyx) | Cross-check synchronous depth call and data type; copy the returned ring buffer |
| Open3D environment | [Open3D 0.19 installation](https://www.open3d.org/docs/0.19.0/getting_started.html) | Conservative Python 3.10–3.12 reference environment |
| Registration | [Open3D ICP API](https://www.open3d.org/docs/0.19.0/python_api/open3d.pipelines.registration.registration_icp.html) | Reuse point-to-plane registration, not a new ICP implementation |
| TSDF | [Open3D ScalableTSDFVolume](https://www.open3d.org/docs/0.19.0/python_api/open3d.pipelines.integration.ScalableTSDFVolume.html) | Reuse the volume and surface extraction |
| Pose convention | [Open3D integration example](https://www.open3d.org/docs/0.19.0/tutorial/pipelines/rgbd_integration.html) | Invert `T_world_from_camera` for integration |
| GLib packages | [Ubuntu 22.04](https://packages.ubuntu.com/jammy/libglib2.0-0), [Ubuntu 24.04](https://packages.ubuntu.com/noble/libglib2.0-0t64) | Choose the package name by supported Ubuntu release |

## What is newly authored

The CLI, ctypes/process isolation, masks, record format, turntable integration, measurement reporting, simple geometry writers, and tests were authored for this delivery. They are not represented as a clone of a hardware-tested existing scanner.

The difficult general reconstruction algorithms are reused from Open3D. The low-level USB protocol implementation is reused from libfreenect. The code does not contain proprietary Kinect SDK binaries, firmware, or third-party game assets.

## Licensing

The new code is MIT-licensed. Consult each installed dependency's own license. libfreenect's upstream license choices and redistribution rules are in its repository; Open3D's license is in its repository. The earlier linked applications, data, games, Unity assets, and repositories remain separately licensed. A public repository URL is not automatic permission to redistribute every included asset.


---

<a id="ubuntu-source"></a>
# F. Complete source code

# Complete Ubuntu scanner source code

**Version:** 0.1.0  
**Hardware:** original Kinect v1  
**Date:** November 17, 2026

Every implementation, installer, configuration, and automated-test file is included below without abbreviation. The ZIP contains these files in their executable directory structure. Read the installation guide and validation report before connecting hardware. This code does not include an external library implementation, a proprietary SDK, firmware, or game assets.

## File index

- [pyproject.toml](#source-file-1)
- [requirements-ubuntu.txt](#source-file-2)
- [.gitignore](#source-file-3)
- [LICENSE](#source-file-4)
- [config/99-kinectscan.rules](#source-file-5)
- [scripts/install_ubuntu.sh](#source-file-6)
- [scripts/smoke_test.sh](#source-file-7)
- [src/kinectscan/__init__.py](#source-file-8)
- [src/kinectscan/__main__.py](#source-file-9)
- [src/kinectscan/capture.py](#source-file-10)
- [src/kinectscan/cli.py](#source-file-11)
- [src/kinectscan/geometry.py](#source-file-12)
- [src/kinectscan/reconstruct.py](#source-file-13)
- [src/kinectscan/storage.py](#source-file-14)
- [src/kinectscan/synthetic.py](#source-file-15)
- [tests/test_capture_binding.py](#source-file-16)
- [tests/test_geometry.py](#source-file-17)
- [tests/test_open3d_optional.py](#source-file-18)
- [tests/test_storage_cli.py](#source-file-19)

---

<a id="source-file-1"></a>
## `pyproject.toml`

`````toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "kinect-v1-ubuntu-scanner"
version = "0.1.0"
description = "Fixed Kinect v1 capture, observed-surface measurement, and multi-view reconstruction for Ubuntu"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
dependencies = ["numpy>=1.26,<3", "scipy>=1.11,<2"]

[project.optional-dependencies]
reconstruction = ["open3d==0.19.0"]
gui = ["opencv-python==4.10.0.84"]
test = ["pytest>=8,<9"]

[project.scripts]
kinectscan = "kinectscan.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
`````

---

<a id="source-file-2"></a>
## `requirements-ubuntu.txt`

`````text
# Conservative Python 3.10-3.12 reference environment, not a claim of latest versions.
numpy==1.26.4
scipy==1.13.1
open3d==0.19.0
opencv-python==4.10.0.84
pytest==8.3.5
`````

---

<a id="source-file-3"></a>
## `.gitignore`

`````text
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
*.egg-info/
build/
dist/
runs/
!examples/
`````

---

<a id="source-file-4"></a>
## `LICENSE`

`````text
MIT License

Copyright (c) 2026 Contributors to this generated reference implementation

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
`````

---

<a id="source-file-5"></a>
## `config/99-kinectscan.rules`

`````text
# Access only these Kinect v1 USB functions; do not make all USB devices world writable.
# IDs cross-checked against upstream OpenKinect/platform/linux/udev/51-kinect.rules.
SUBSYSTEM=="usb", ATTR{idVendor}=="045e", ATTR{idProduct}=="02b0", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="045e", ATTR{idProduct}=="02ad", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="045e", ATTR{idProduct}=="02ae", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="045e", ATTR{idProduct}=="02c2", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="045e", ATTR{idProduct}=="02be", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="045e", ATTR{idProduct}=="02bf", MODE="0660", GROUP="plugdev", TAG+="uaccess"
`````

---

<a id="source-file-6"></a>
## `scripts/install_ubuntu.sh`

`````bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$(id -u)" -eq 0 ]; then
  echo "Run this script as your normal desktop user, not with sudo. It asks sudo only for apt/udev changes." >&2
  exit 1
fi
. /etc/os-release
if [ "${ID:-}" != "ubuntu" ]; then
  echo "Reference installer targets Ubuntu 22.04/24.04. Review README for manual installation on another system." >&2
  exit 1
fi
case "${VERSION_ID:-}" in
  22.04) GLIB_PACKAGE="libglib2.0-0" ;;
  24.04) GLIB_PACKAGE="libglib2.0-0t64" ;;
  *) echo "Reference installer is limited to Ubuntu 22.04/24.04. Review manual setup for other releases." >&2; exit 1 ;;
esac
if [ "$(uname -m)" != "x86_64" ]; then
  echo "Reference full-stack wheels target x86-64. Review dependencies manually on other architectures." >&2
  exit 1
fi
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" - <<'PY'
import sys
if not (3,10) <= sys.version_info[:2] <= (3,12):
    raise SystemExit('Reference full stack requires Python 3.10-3.12. Set PYTHON_BIN to an installed compatible interpreter; do not replace system Python.')
PY
sudo apt-get update
sudo apt-get install -y software-properties-common
sudo add-apt-repository -y universe
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev libfreenect-dev libfreenect-bin libusb-1.0-0 usbutils libgl1 "$GLIB_PACKAGE"
if ! getent group plugdev >/dev/null; then sudo groupadd --system plugdev; fi
sudo usermod -aG plugdev "$(id -un)"
sudo install -m 0644 config/99-kinectscan.rules /etc/udev/rules.d/99-kinectscan.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=045e
"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install --only-binary=:all: -r requirements-ubuntu.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m pip freeze > installed-versions.txt
echo "Installation complete. Log out/in for plugdev membership, then unplug/replug Kinect."
echo "Connect the Kinect v1 external power adapter. Do not run scanner as root."
echo "Next: source .venv/bin/activate && kinectscan doctor && kinectscan probe --out intrinsics.json"
`````

---

<a id="source-file-7"></a>
## `scripts/smoke_test.sh`

`````bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
OUT="${1:-runs/synthetic-smoke}"
"$PYTHON_BIN" -m pytest -q
"$PYTHON_BIN" -m kinectscan demo --out "$OUT/session" --step-deg 10
"$PYTHON_BIN" -m kinectscan snapshot --input "$OUT/session/frames/000000.npz" --out "$OUT/snapshot" --z-min 0.7 --z-max 2.0 --stride 1
"$PYTHON_BIN" -m kinectscan fuse-known --session "$OUT/session" --out "$OUT/fused-cloud"
echo "Synthetic smoke test complete. This does not validate USB hardware or Open3D TSDF."
`````

---

<a id="source-file-8"></a>
## `src/kinectscan/__init__.py`

`````python
"""Geometry-first Kinect v1 scanner. No hardware is opened at import time."""
__version__ = "0.1.0"
`````

---

<a id="source-file-9"></a>
## `src/kinectscan/__main__.py`

`````python
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
`````

---

<a id="source-file-10"></a>
## `src/kinectscan/capture.py`

`````python
"""libfreenect synchronous C API behind a killable worker process.

Using ctypes avoids relying on abandoned Python 2-era freenect wheels. No
hand-copied device-struct ABI and no guessed focal length are used.
"""
from __future__ import annotations
import ctypes as ct
import ctypes.util
import multiprocessing as mp
import time
import numpy as np
from .geometry import Intrinsics, median_depth

WIDTH, HEIGHT = 640, 480
FREENECT_DEPTH_MM = 5


def library_path():
    return ctypes.util.find_library("freenect_sync")


class _Native:
    def __init__(self, index: int):
        name = library_path()
        if not name:
            raise RuntimeError("libfreenect_sync not found. Install libfreenect-dev and libfreenect-bin, then run ldconfig if built from source.")
        self.lib = ct.CDLL(name)
        self.index = int(index)
        self.lib.freenect_sync_get_depth.argtypes = [ct.POINTER(ct.c_void_p),ct.POINTER(ct.c_uint32),ct.c_int,ct.c_int]
        self.lib.freenect_sync_get_depth.restype = ct.c_int
        self.lib.freenect_sync_stop.argtypes = []
        self.lib.freenect_sync_stop.restype = None

    def read(self):
        ptr = ct.c_void_p(); stamp = ct.c_uint32()
        rc = self.lib.freenect_sync_get_depth(ct.byref(ptr),ct.byref(stamp),self.index,FREENECT_DEPTH_MM)
        if rc != 0 or not ptr.value:
            raise RuntimeError(f"Kinect depth read failed ({rc}). Check external power, USB, udev permissions and other camera applications.")
        # Own the memory before requesting another frame; the native ring buffer is reused.
        data = np.ctypeslib.as_array(ct.cast(ptr,ct.POINTER(ct.c_uint16)),shape=(HEIGHT*WIDTH,)).reshape(HEIGHT,WIDTH).copy()
        data[(data == 0) | (data >= 10000)] = 0
        return data, int(stamp.value)

    def intrinsics(self):
        if not hasattr(self.lib,"freenect_sync_camera_to_world"):
            raise RuntimeError("This libfreenect lacks freenect_sync_camera_to_world. Supply independently calibrated --intrinsics JSON, or build a newer official libfreenect. No guessed intrinsics will be substituted.")
        f = self.lib.freenect_sync_camera_to_world
        f.argtypes = [ct.c_int,ct.c_int,ct.c_int,ct.POINTER(ct.c_double),ct.POINTER(ct.c_double),ct.c_int]
        f.restype = ct.c_int
        def world(u,v):
            x,y = ct.c_double(),ct.c_double()
            if f(u,v,1000,ct.byref(x),ct.byref(y),self.index) != 0:
                raise RuntimeError("Factory projection query failed")
            return x.value,y.value
        x0,y0 = world(320,240); x1,y1 = world(321,241)
        if abs(x1-x0)<1e-9 or abs(y1-y0)<1e-9:
            raise RuntimeError("Invalid factory ray mapping")
        fx,fy = 1000/(x1-x0),1000/(y1-y0)
        cx,cy = 320-x0*fx/1000,240-y0*fy/1000
        return Intrinsics(WIDTH,HEIGHT,fx,fy,cx,cy,
            source="libfreenect device-specific factory camera_to_world model; not independent metrology calibration")

    def close(self):
        self.lib.freenect_sync_stop()


def _worker(conn,index,override):
    native = None
    try:
        native = _Native(index)
        native.read()  # Initializes the device / factory registration.
        k = Intrinsics.from_dict(override) if override else native.intrinsics()
        if (k.width,k.height)!=(WIDTH,HEIGHT):
            raise ValueError("Kinect medium mode requires 640x480 IR intrinsics")
        conn.send(("ready",k.to_dict()))
        while True:
            cmd = conn.recv()
            if cmd == "stop": break
            if cmd != "read": raise ValueError("Unknown acquisition command")
            depth,stamp = native.read()
            conn.send(("frame",depth,stamp,time.monotonic()))
    except (EOFError,BrokenPipeError):
        pass
    except BaseException as exc:
        try: conn.send(("error",f"{type(exc).__name__}: {exc}"))
        except (BrokenPipeError,EOFError,OSError): pass
    finally:
        if native is not None:
            native.close()
        conn.close()


class KinectCapture:
    """One process owns one sensor. Reads time out instead of hanging the CLI."""
    def __init__(self,index=0,timeout=10.,intrinsics=None):
        if index < 0 or timeout <= 0: raise ValueError("Invalid device index or timeout")
        self.index=index; self.timeout=timeout; self.override=intrinsics
        self.process=None; self.conn=None; self.k=None; self.last_timestamp=None

    def __enter__(self):
        ctx=mp.get_context("spawn"); parent,child=ctx.Pipe()
        self.conn=parent
        self.process=ctx.Process(target=_worker,args=(child,self.index,
            self.override.to_dict() if self.override else None),daemon=True)
        self.process.start(); child.close()
        try:
            msg=self._receive()
            if msg[0]!="ready": raise RuntimeError(f"Unexpected worker reply: {msg[0]}")
            self.k=Intrinsics.from_dict(msg[1])
            return self
        except BaseException:
            self.close(); raise

    def _receive(self):
        if not self.conn.poll(self.timeout):
            raise TimeoutError("Kinect worker timed out. Check power, permissions and USB. The worker will be terminated on exit.")
        try: msg=self.conn.recv()
        except EOFError as exc: raise RuntimeError("Kinect worker exited unexpectedly") from exc
        if msg[0]=="error": raise RuntimeError(msg[1])
        return msg

    def read(self):
        for _ in range(5):
            self.conn.send("read"); msg=self._receive()
            if msg[0]!="frame": raise RuntimeError("Unexpected capture reply")
            depth,stamp,host=msg[1:]
            if stamp!=self.last_timestamp:
                self.last_timestamp=stamp
                return depth,stamp,host
        raise RuntimeError("Repeated device timestamp: no fresh depth frames")

    def median(self,samples=15,max_std_mm=None):
        if not 1 <= samples <= 120: raise ValueError("samples must be 1..120")
        frames=[]
        for _ in range(samples):
            depth,stamp,host=self.read(); frames.append(depth)
        return median_depth(frames,max_std_mm=max_std_mm),stamp,host

    def close(self):
        if self.conn is not None:
            try: self.conn.send("stop")
            except (BrokenPipeError,EOFError,OSError): pass
        if self.process is not None:
            self.process.join(timeout=1.)
            if self.process.is_alive():
                self.process.terminate(); self.process.join(timeout=2.)
            if self.process.is_alive():
                self.process.kill(); self.process.join(timeout=1.)
        if self.conn is not None: self.conn.close()
        self.process=None; self.conn=None

    def __exit__(self,*exc):
        self.close()
`````

---

<a id="source-file-11"></a>
## `src/kinectscan/cli.py`

`````python
"""Command-line entry point. Hardware and graphical imports are lazy."""
from __future__ import annotations
import argparse
from dataclasses import replace
import importlib.metadata
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import time
import numpy as np
from .capture import KinectCapture,library_path
from .geometry import (Intrinsics,rectify_depth,segment_depth,depth_to_xyz,grid_mesh,
                        measurement_report,fit_axis_circle,turntable_pose)
from .storage import (new_directory,save_frame,load_frame,write_json,export_geometry,
                       write_mesh)


def _sensor(args):
    k=Intrinsics.load(args.intrinsics) if args.intrinsics else None
    return KinectCapture(index=args.device,timeout=args.timeout,intrinsics=k)


def _processed(depth,k,args):
    rectified=rectify_depth(depth,k)
    rk=replace(k,distortion=())
    bg=None
    if args.background:
        bg,bk,_=load_frame(args.background)
        if (bk.width,bk.height)!=(rk.width,rk.height) or not np.allclose(bk.matrix,rk.matrix):
            raise ValueError("Background and capture intrinsics differ; recapture the background")
        if bk.distortion and not np.allclose(bk.distortion,0):
            raise ValueError("Background must already be rectified")
    filtered=segment_depth(rectified,rk,z_min=args.z_min,z_max=args.z_max,roi=args.roi,
            box=args.box,background=bg,background_margin_mm=args.background_margin_mm,
            largest_component=args.largest_component)
    return filtered,rk


def _summary(data):
    print(json.dumps(data,indent=2,allow_nan=False))


def doctor(args):
    versions={}
    for name in ("numpy","scipy","open3d","opencv-python"):
        try: versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name]="not installed"
    usb="lsusb not installed"
    if shutil.which("lsusb"):
        result=subprocess.run(["lsusb"],capture_output=True,text=True,timeout=5,check=False)
        usb="\n".join(line for line in result.stdout.splitlines() if "045e:" in line) or "No Microsoft USB devices listed"
    _summary({"system":platform.platform(),"python":sys.version,"packages":versions,
        "libfreenect_sync":library_path(),"microsoft_usb_devices":usb,
        "note":"This does not open the camera. Run probe for a live connection test."})


def probe(args):
    with _sensor(args) as camera:
        for _ in range(5): depth,stamp,host=camera.read()
        k=camera.k
        valid=(depth>0)&(depth<10000)
        if not valid.any(): raise RuntimeError("Device opened but depth is all invalid. Check range, IR conditions and power.")
        if args.out:
            if Path(args.out).exists(): raise FileExistsError(args.out)
            k.save(args.out)
        _summary({"intrinsics":k.to_dict(),"valid_fraction":float(valid.mean()),
                  "median_depth_m":float(np.median(depth[valid])/1000),"timestamp":stamp,
                  "warning":"Connection success is not a calibration/accuracy certificate."})


def background(args):
    path=Path(args.out)
    if path.exists(): raise FileExistsError(path)
    with _sensor(args) as camera:
        print("Keep the scan region empty and the sensor/support/background fixed.")
        time.sleep(args.delay)
        raw,stamp,host=camera.median(args.samples,max_std_mm=args.max_std_mm)
        depth=rectify_depth(raw,camera.k); k=replace(camera.k,distortion=())
        save_frame(path,depth,k,raw=raw,timestamp=stamp,host_time=host)
        write_json(path.with_suffix(".metadata.json"),{"capture_intrinsics":camera.k.to_dict(),
            "samples":args.samples,"description":"Empty scene; median depth; zeros remain unobserved."})
        _summary({"saved":str(path),"valid_fraction":float((depth>0).mean())})


def _snapshot_write(out,raw,k,stamp,host,args):
    filtered,rk=_processed(raw,k,args)
    xyz=depth_to_xyz(filtered,rk).reshape(-1,3); xyz=xyz[np.isfinite(xyz).all(axis=1)]
    if len(xyz)<args.min_points: raise ValueError("Too few foreground points. Inspect preview/ROI/depth range/background.")
    out=new_directory(out)
    vertices,triangles=grid_mesh(filtered,rk,stride=args.stride,max_edge_m=args.max_edge_m)
    save_frame(out/"frame.npz",filtered,rk,raw=raw,timestamp=stamp,host_time=host)
    k.save(out/"capture_intrinsics.json")
    export_geometry(out,xyz,vertices,triangles)
    report=measurement_report(xyz)
    report["mesh_is_observed_surface_only"]=True
    report["mesh_triangles"]=len(triangles)
    report["print_readiness"]="Not guaranteed; front-surface mesh is generally open. Hidden surfaces are not fabricated."
    write_json(out/"measurements.json",report)
    _summary(report)


def snapshot(args):
    if args.input:
        depth,k,_=load_frame(args.input)
        _snapshot_write(args.out,depth,k,0,0.,args)
    else:
        with _sensor(args) as camera:
            time.sleep(args.delay)
            depth,stamp,host=camera.median(args.samples,max_std_mm=args.max_std_mm)
            _snapshot_write(args.out,depth,camera.k,stamp,host,args)


def preview(args):
    try: import cv2
    except ImportError as exc: raise RuntimeError("Install opencv-python / the gui extra") from exc
    with _sensor(args) as camera:
        try:
            while True:
                raw,_,_=camera.read(); depth,k=_processed(raw,camera.k,args)
                scale=np.clip((depth.astype(float)/1000-args.z_min)/(args.z_max-args.z_min),0,1)
                image=cv2.applyColorMap((255*scale).astype(np.uint8),cv2.COLORMAP_TURBO)
                image[depth==0]=0
                cv2.putText(image,f"Valid {(depth>0).mean():.1%} | depth mm | Q/ESC exits",(12,24),
                            cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1)
                if args.roi:
                    x0,y0,x1,y1=args.roi; cv2.rectangle(image,(x0,y0),(x1-1,y1-1),(255,255,255),1)
                cv2.imshow("Kinect v1 depth (X right, Y down)",image)
                key=cv2.waitKey(1)&255
                if key in (ord("q"),27): break
        finally: cv2.destroyAllWindows()


def _manifest(k,args,motion):
    return {"schema_version":1,"synthetic":False,"subject_motion":motion,
        "foreground_isolated":bool(args.background or args.roi or args.box),
        "capture_intrinsics":k.to_dict(),"depth_unit":"millimeter",
        "pose_convention":"T_world_from_camera; world=angle-zero camera frame; meters",
        "segmentation":{"roi":args.roi,"box":args.box,"background":args.background,
                        "z_min":args.z_min,"z_max":args.z_max,"background_margin_mm":args.background_margin_mm,
                        "largest_component":args.largest_component},
        "frames":[],"completed":False,
        "warning":"Foreground_isolated records requested cropping, not successful semantic segmentation. Inspect every mask."}


def record(args):
    if args.seconds<=0 or not 0<args.fps<=30 or args.seconds*args.fps>1200:
        raise ValueError("Require duration>0, FPS in (0,30], and at most 1200 requested frames")
    out=new_directory(args.out); (out/"frames").mkdir()
    with _sensor(args) as camera:
        manifest=_manifest(camera.k,args,"stationary" if args.stationary else "unknown_rotating_subject")
        write_json(out/"session.json",manifest)
        time.sleep(args.delay); start=time.monotonic(); i=0
        try:
            while time.monotonic()-start<args.seconds:
                raw,stamp,host=camera.read(); depth,k=_processed(raw,camera.k,args)
                if np.count_nonzero(depth)<args.min_points:
                    raise RuntimeError(f"Frame {i} has too few foreground points; stopped rather than record an unusable session")
                rel=f"frames/{i:06d}.npz"
                save_frame(out/rel,depth,k,raw=raw,timestamp=stamp,host_time=host)
                manifest["frames"].append({"path":rel,"device_timestamp":stamp,"host_monotonic_s":host})
                write_json(out/"session.json",manifest)
                i+=1; print(f"Captured {i} frames",end="\r",flush=True)
                time.sleep(max(0,start+i/args.fps-time.monotonic()))
            manifest["completed"]=True
        finally:
            write_json(out/"session.json",manifest); print()
    _summary({"session":str(out),"frames":len(manifest["frames"]),"completed":manifest["completed"]})


def turntable(args):
    if not 0<args.step_deg<=20 or not np.isclose(360/args.step_deg,round(360/args.step_deg)):
        raise ValueError("Use a positive angle <=20 degrees that divides 360")
    axis=json.loads(Path(args.axis).read_text())
    if axis.get("observed_arc_deg",0)<180:
        raise ValueError("Axis calibration must cover at least 180 degrees")
    # Validate axis/center before creating a recording.
    turntable_pose(0,axis["center_m"],axis["axis"])
    out=new_directory(args.out); (out/"frames").mkdir()
    with _sensor(args) as camera:
        manifest=_manifest(camera.k,args,"known_turntable")
        manifest["turntable_axis"]=axis
        manifest["angle_source"]="manual indexed stop-and-hold; commanded angles are assumed, not encoder-measured"
        write_json(out/"session.json",manifest)
        try:
            angles=np.linspace(0,360,int(round(360/args.step_deg))+1)
            for i,angle in enumerate(angles):
                input(f"Place object at {angle:.1f} deg using the documented right-hand sign; stop motion; press Enter: ")
                time.sleep(args.settle_sec)
                raw,stamp,host=camera.median(args.samples,max_std_mm=args.max_std_mm)
                depth,k=_processed(raw,camera.k,args)
                if np.count_nonzero(depth)<args.min_points: raise RuntimeError("Too few foreground samples")
                rel=f"frames/{i:06d}.npz"; pose=turntable_pose(angle,axis["center_m"],axis["axis"])
                save_frame(out/rel,depth,k,raw=raw,timestamp=stamp,host_time=host,pose=pose)
                manifest["frames"].append({"path":rel,"angle_deg":float(angle),"device_timestamp":stamp,"host_monotonic_s":host})
                write_json(out/"session.json",manifest)
            manifest["completed"]=True
        finally: write_json(out/"session.json",manifest)
    _summary({"session":str(out),"frames":len(manifest["frames"])})


def axis_fit(args):
    points=np.loadtxt(args.points,delimiter=",",skiprows=args.skiprows,ndmin=2)
    if args.input_units=="mm": points=points/1000.
    result=fit_axis_circle(points,args.preferred_axis)
    if result["observed_arc_deg"]<180: raise ValueError("Orbit coverage <180 degrees; acquire more viewpoints")
    if result["rms_residual_mm"]>args.max_rms_mm: raise ValueError(f"Axis fit residual is {result['rms_residual_mm']:.2f} mm; exceeds threshold")
    if Path(args.out).exists(): raise FileExistsError(args.out)
    write_json(args.out,result); _summary(result)


def measure(args):
    depth,k,_=load_frame(args.input)
    if k.distortion and not np.allclose(k.distortion,0):
        raise ValueError("Select points on a rectified captured frame")
    def point(pixel):
        u,v=pixel
        if not 0<=u<k.width or not 0<=v<k.height: raise ValueError("Pixel outside frame")
        r=args.radius
        patch=depth[max(0,v-r):min(k.height,v+r+1),max(0,u-r):min(k.width,u+r+1)]
        good=patch[(patch>0)&(patch<10000)]
        if not len(good): raise ValueError(f"No valid depth at pixel {pixel}; no hidden/nearby point is guessed")
        z=float(np.median(good))/1000
        return np.array([(u-k.cx)*z/k.fx,(v-k.cy)*z/k.fy,z])
    p1,p2=point(args.p1),point(args.p2)
    result={"point1_m":p1.tolist(),"point2_m":p2.tolist(),"distance_mm":float(np.linalg.norm(p2-p1)*1000),
            "pixel1":args.p1,"pixel2":args.p2,"patch_radius":args.radius,
            "warning":"Visible-point Euclidean distance. A patch median assumes locally uniform depth; avoid boundaries."}
    if args.out: write_json(args.out,result)
    _summary(result)


def reconstruct_command(args):
    from .reconstruct import reconstruct
    _summary(reconstruct(args.session,args.out,args.mode,voxel_m=args.voxel_m,
          min_fitness=args.min_fitness,max_rmse_m=args.max_rmse_m,
          max_rotation_deg=args.max_rotation_deg,max_translation_m=args.max_translation_m,
          close_loop=args.close_loop))


def fuse_known(args):
    from .reconstruct import fuse_known_clouds
    _summary(fuse_known_clouds(args.session,args.out,args.voxel_m))


def demo(args):
    from .synthetic import create_demo
    manifest=create_demo(args.out,args.step_deg)
    _summary({"synthetic":True,"frames":len(manifest["frames"]),"out":args.out,
              "next":"Use fuse-known for point fusion or reconstruct --mode known with Open3D."})


def view(args):
    from .reconstruct import open3d_module
    o3d=open3d_module(); mesh=o3d.io.read_triangle_mesh(args.input)
    if len(mesh.triangles): mesh.compute_vertex_normals(); obj=mesh
    else: obj=o3d.io.read_point_cloud(args.input)
    if obj.is_empty(): raise ValueError("No displayable geometry")
    o3d.visualization.draw_geometries([obj],window_name="KinectScan geometry")


def convert(args):
    from .reconstruct import open3d_module
    if Path(args.out).exists(): raise FileExistsError(args.out)
    o3d=open3d_module(); mesh=o3d.io.read_triangle_mesh(args.input)
    if not len(mesh.triangles): raise ValueError("Input has no triangles. A point cloud is not an STL mesh.")
    scale=.001 if args.input_units=="mm" else 1.
    write_mesh(args.out,np.asarray(mesh.vertices)*scale,np.asarray(mesh.triangles),stl_units=args.stl_units)
    _summary({"output":args.out,"note":"Geometry-only conversion; no hole filling, texture conversion or CAD reverse engineering."})


def mesh_check(args):
    from .reconstruct import open3d_module
    o3d=open3d_module(); mesh=o3d.io.read_triangle_mesh(args.input)
    if not len(mesh.triangles): raise ValueError("No triangles")
    result={"vertices":len(mesh.vertices),"triangles":len(mesh.triangles),
            "edge_manifold_without_boundaries":bool(mesh.is_edge_manifold(allow_boundary_edges=False)),
            "vertex_manifold":bool(mesh.is_vertex_manifold()),"watertight":bool(mesh.is_watertight()),
            "orientable":bool(mesh.is_orientable()),
            "warning":"Topology checks do not prove measured coverage, dimensional accuracy, or printer suitability."}
    if args.out: write_json(args.out,result)
    _summary(result)


def _sensor_args(p):
    p.add_argument("--device",type=int,default=0)
    p.add_argument("--timeout",type=float,default=10.)
    p.add_argument("--intrinsics",help="Calibrated IR FREENECT_DEPTH_MM JSON; otherwise query device factory ray model")


def _segmentation_args(p):
    p.add_argument("--z-min",type=float,default=.7)
    p.add_argument("--z-max",type=float,default=3.5)
    p.add_argument("--roi",type=int,nargs=4,metavar=("X0","Y0","X1","Y1"))
    p.add_argument("--box",type=float,nargs=6,metavar=("XMIN","XMAX","YMIN","YMAX","ZMIN","ZMAX"))
    p.add_argument("--background",help="Empty-scene .npz from background command")
    p.add_argument("--background-margin-mm",type=float,default=25.)
    p.add_argument("--largest-component",action="store_true",help="Keep only largest connected depth silhouette; can discard disconnected limbs")
    p.add_argument("--min-points",type=int,default=200)


def _samples_args(p):
    p.add_argument("--samples",type=int,default=15)
    p.add_argument("--max-std-mm",type=float,default=None,help="Reject temporally unstable pixels; only use while subject is still")


def parser():
    p=argparse.ArgumentParser(description="Fixed Kinect v1 / Ubuntu geometry scanner. See README for limitations.")
    sub=p.add_subparsers(dest="command",required=True)
    q=sub.add_parser("doctor",help="Inspect environment without opening hardware"); q.set_defaults(func=doctor)
    q=sub.add_parser("probe",help="Connect and query factory ray intrinsics"); _sensor_args(q); q.add_argument("--out"); q.set_defaults(func=probe)
    q=sub.add_parser("preview",help="Live masked depth preview"); _sensor_args(q); _segmentation_args(q); q.set_defaults(func=preview)
    q=sub.add_parser("background",help="Capture an empty-scene background"); _sensor_args(q); _samples_args(q)
    q.add_argument("--out",required=True); q.add_argument("--delay",type=float,default=3.); q.set_defaults(func=background)
    q=sub.add_parser("snapshot",help="Observed points/mesh and measurements from one stationary view")
    _sensor_args(q); _segmentation_args(q); _samples_args(q)
    q.add_argument("--input",help="Offline .npz replay instead of hardware")
    q.add_argument("--out",required=True); q.add_argument("--delay",type=float,default=3.)
    q.add_argument("--stride",type=int,default=2); q.add_argument("--max-edge-m",type=float,default=.04); q.set_defaults(func=snapshot)
    q=sub.add_parser("record",help="Fixed camera, slowly rotating subject; estimate relative poses later")
    _sensor_args(q); _segmentation_args(q); q.add_argument("--out",required=True)
    q.add_argument("--seconds",type=float,default=60.); q.add_argument("--fps",type=float,default=5.)
    q.add_argument("--delay",type=float,default=5.); q.add_argument("--stationary",action="store_true",help="Assert BOTH camera and subject remain stationary")
    q.set_defaults(func=record)
    q=sub.add_parser("axis-fit",help="Fit turntable axis from tracked off-axis target XYZ samples")
    q.add_argument("--points",required=True); q.add_argument("--out",required=True)
    q.add_argument("--skiprows",type=int,default=1); q.add_argument("--input-units",choices=("m","mm"),default="m")
    q.add_argument("--preferred-axis",type=float,nargs=3,default=[0.,-1.,0.])
    q.add_argument("--max-rms-mm",type=float,default=10.); q.set_defaults(func=axis_fit)
    q=sub.add_parser("turntable",help="Manually indexed step-and-hold product scan; no motor driver")
    _sensor_args(q); _segmentation_args(q); _samples_args(q)
    q.add_argument("--axis",required=True); q.add_argument("--out",required=True)
    q.add_argument("--step-deg",type=float,default=10.); q.add_argument("--settle-sec",type=float,default=.7)
    q.set_defaults(func=turntable)
    q=sub.add_parser("measure",help="Distance between two visible pixels in a saved frame")
    q.add_argument("--input",required=True); q.add_argument("--p1",type=int,nargs=2,required=True)
    q.add_argument("--p2",type=int,nargs=2,required=True); q.add_argument("--radius",type=int,default=0)
    q.add_argument("--out"); q.set_defaults(func=measure)
    q=sub.add_parser("reconstruct",help="Open3D TSDF mesh with explicit relative-pose mode")
    q.add_argument("--session",required=True); q.add_argument("--out",required=True)
    q.add_argument("--mode",choices=("auto","known","static"),required=True)
    q.add_argument("--voxel-m",type=float,default=.006); q.add_argument("--min-fitness",type=float,default=.6)
    q.add_argument("--max-rmse-m",type=float,default=.02); q.add_argument("--max-rotation-deg",type=float,default=25.)
    q.add_argument("--max-translation-m",type=float,default=.30); q.add_argument("--close-loop",action="store_true")
    q.set_defaults(func=reconstruct_command)
    q=sub.add_parser("fuse-known",help="Known-pose multi-view point fusion without Open3D")
    q.add_argument("--session",required=True); q.add_argument("--out",required=True)
    q.add_argument("--voxel-m",type=float,default=.005); q.set_defaults(func=fuse_known)
    q=sub.add_parser("demo",help="Create clearly labeled synthetic test session; no camera required")
    q.add_argument("--out",required=True); q.add_argument("--step-deg",type=int,default=10); q.set_defaults(func=demo)
    q=sub.add_parser("view",help="Open a point cloud or mesh with Open3D")
    q.add_argument("--input",required=True); q.set_defaults(func=view)
    q=sub.add_parser("convert",help="Convert geometry mesh formats with explicit input units")
    q.add_argument("--input",required=True); q.add_argument("--out",required=True)
    q.add_argument("--input-units",choices=("m","mm"),required=True); q.add_argument("--stl-units",choices=("m","mm"),default="mm")
    q.set_defaults(func=convert)
    q=sub.add_parser("mesh-check",help="Check topology; does not certify printing or measurements")
    q.add_argument("--input",required=True); q.add_argument("--out"); q.set_defaults(func=mesh_check)
    return p


def main(argv=None):
    p=parser(); args=p.parse_args(argv)
    try:
        for name in ("delay","settle_sec","radius","skiprows"):
            if hasattr(args,name) and getattr(args,name)<0: raise ValueError(f"{name} cannot be negative")
        if hasattr(args,"min_points") and args.min_points<3: raise ValueError("min_points must be >=3")
        args.func(args)
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted. Completed frame files/manifests are retained; acquisition is closed.",file=sys.stderr)
        return 130
    except (RuntimeError,ValueError,OSError,KeyError,EOFError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
`````

---

<a id="source-file-12"></a>
## `src/kinectscan/geometry.py`

`````python
"""Metric geometry. Camera coordinates: +X right, +Y down, +Z forward."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import json
from pathlib import Path
import warnings
import numpy as np
from scipy import ndimage

@dataclass(frozen=True)
class Intrinsics:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    source: str = "user-supplied"
    distortion: tuple[float, ...] = ()
    depth_format: str = "FREENECT_DEPTH_MM"

    def __post_init__(self):
        if self.width <= 1 or self.height <= 1:
            raise ValueError("Image dimensions must exceed one pixel")
        values = np.array([self.fx, self.fy, self.cx, self.cy], float)
        if not np.isfinite(values).all() or min(self.fx, self.fy) <= 0:
            raise ValueError("Invalid camera intrinsics")
        if self.depth_format != "FREENECT_DEPTH_MM":
            raise ValueError("This application accepts IR-frame metric depth, not registered RGB depth")
        if len(self.distortion) not in (0, 4, 5, 8):
            raise ValueError("Distortion must contain 0, 4, 5 or 8 OpenCV coefficients")
        if not np.isfinite(self.distortion).all():
            raise ValueError("Nonfinite distortion coefficients")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        fields = dict(data)
        fields["distortion"] = tuple(fields.get("distortion", ()))
        return cls(**fields)

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text()))

    def save(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    @property
    def matrix(self):
        return np.array([[self.fx, 0., self.cx], [0., self.fy, self.cy], [0., 0., 1.]])


def validate_depth(depth, k: Intrinsics):
    depth = np.asarray(depth)
    if depth.shape != (k.height, k.width) or depth.dtype != np.uint16:
        raise ValueError(f"Expected uint16 depth {(k.height, k.width)}, received {depth.dtype} {depth.shape}")
    return depth


def median_depth(frames, min_fraction=0.7, max_std_mm=None):
    if not frames or not 0 < min_fraction <= 1:
        raise ValueError("Need frames and min_fraction in (0,1]")
    a = np.stack(frames).astype(np.float32)
    valid = (a > 0) & (a < 10000)
    a[~valid] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(a, axis=0)
        std = np.nanstd(a, axis=0)
    keep = valid.sum(axis=0) >= int(np.ceil(len(frames) * min_fraction))
    if max_std_mm is not None:
        if max_std_mm <= 0:
            raise ValueError("max_std_mm must be positive")
        keep &= std <= max_std_mm
    med[~keep | ~np.isfinite(med)] = 0
    return np.rint(med).astype(np.uint16)


def rectify_depth(depth, k: Intrinsics):
    """Nearest-neighbor remap: never interpolate across missing depth."""
    validate_depth(depth, k)
    if not k.distortion or np.allclose(k.distortion, 0):
        return depth.copy()
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("Install the gui extra / opencv-python to rectify calibrated distortion") from exc
    mx, my = cv2.initUndistortRectifyMap(k.matrix, np.asarray(k.distortion), None,
                                       k.matrix, (k.width, k.height), cv2.CV_32FC1)
    return cv2.remap(depth, mx, my, interpolation=cv2.INTER_NEAREST,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def depth_to_xyz(depth, k: Intrinsics):
    """Input uint16 millimeters; output HxWx3 meters. Invalid points are NaN."""
    validate_depth(depth, k)
    v, u = np.indices(depth.shape, dtype=np.float64)
    z = depth.astype(np.float64) / 1000.
    points = np.stack(((u-k.cx)*z/k.fx, (v-k.cy)*z/k.fy, z), axis=-1)
    points[(depth == 0) | (depth >= 10000)] = np.nan
    return points


def segment_depth(depth, k: Intrinsics, *, z_min=0.7, z_max=3.5, roi=None,
                  box=None, background=None, background_margin_mm=25.,
                  largest_component=False, min_component_pixels=0):
    """ROI and foreground subtraction; not semantic object recognition."""
    validate_depth(depth, k)
    if not 0 < z_min < z_max < 10:
        raise ValueError("Require 0 < z_min < z_max < 10 meters")
    mask = (depth >= z_min*1000) & (depth <= z_max*1000)
    if roi is not None:
        x0, y0, x1, y1 = map(int, roi)
        if not (0 <= x0 < x1 <= k.width and 0 <= y0 < y1 <= k.height):
            raise ValueError("ROI must be x0 y0 x1 y1 inside the image; end coordinates are exclusive")
        rect = np.zeros_like(mask)
        rect[y0:y1, x0:x1] = True
        mask &= rect
    if background is not None:
        validate_depth(background, k)
        if background_margin_mm <= 0:
            raise ValueError("Background margin must be positive")
        # Unknown background stays unknown: do not silently label it foreground.
        mask &= (background > 0) & (background < 10000)
        mask &= background.astype(np.int32) - depth.astype(np.int32) > background_margin_mm
    if box is not None:
        if len(box) != 6:
            raise ValueError("Box order: xmin xmax ymin ymax zmin zmax, in meters")
        lo = np.array(box[::2], float); hi = np.array(box[1::2], float)
        if not np.isfinite(box).all() or not (hi > lo).all():
            raise ValueError("Invalid 3D crop box")
        xyz = depth_to_xyz(depth, k)
        mask &= ((xyz >= lo) & (xyz <= hi)).all(axis=-1)
    if largest_component or min_component_pixels:
        labels, n = ndimage.label(mask, structure=np.ones((3, 3)))
        if n:
            counts = np.bincount(labels.ravel()); counts[0] = 0
            if largest_component:
                mask &= labels == int(counts.argmax())
            else:
                mask &= counts[labels] >= int(min_component_pixels)
    result = depth.copy(); result[~mask] = 0
    return result


def grid_mesh(depth, k: Intrinsics, stride=2, max_edge_m=0.04):
    """Observed surface only. Never cap boundaries or bridge missing samples."""
    if stride < 1 or max_edge_m <= 0:
        raise ValueError("Positive stride and edge limit required")
    xyz = depth_to_xyz(depth, k)[::stride, ::stride]
    h, w = xyz.shape[:2]
    vertices = xyz.reshape(-1, 3)
    ids = np.arange(h*w).reshape(h, w)
    a, b, c, d = ids[:-1,:-1], ids[:-1,1:], ids[1:,:-1], ids[1:,1:]
    # Normals face the viewing camera (approximately negative Z).
    tri = np.concatenate((np.stack((a,c,b), -1).reshape(-1,3),
                          np.stack((b,c,d), -1).reshape(-1,3)))
    if not len(tri):
        return np.empty((0,3)), np.empty((0,3), dtype=np.int64)
    p = vertices[tri]
    finite = np.isfinite(p).all(axis=(1,2))
    edge = np.maximum.reduce([np.linalg.norm(p[:,0]-p[:,1],axis=1),
                              np.linalg.norm(p[:,1]-p[:,2],axis=1),
                              np.linalg.norm(p[:,2]-p[:,0],axis=1)])
    area2 = np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)
    tri = tri[finite & (edge <= max_edge_m) & (area2 > 1e-12)]
    if not len(tri):
        return np.empty((0,3)), np.empty((0,3), dtype=np.int64)
    used, inverse = np.unique(tri, return_inverse=True)
    return vertices[used], inverse.reshape(-1,3)


def transform_points(points, transform):
    t = validate_transform(transform)
    return np.asarray(points) @ t[:3,:3].T + t[:3,3]


def validate_transform(transform):
    t = np.asarray(transform, dtype=float)
    if t.shape != (4,4) or not np.isfinite(t).all():
        raise ValueError("Expected finite 4x4 rigid transform")
    if not np.allclose(t[3], [0,0,0,1], atol=1e-7):
        raise ValueError("Invalid homogeneous transform")
    r = t[:3,:3]
    if not np.allclose(r.T@r, np.eye(3), atol=1e-5) or not np.isclose(np.linalg.det(r), 1, atol=1e-5):
        raise ValueError("Transform must be rigid with determinant +1 (no scale/reflection)")
    return t


def rotation_axis_angle(axis, angle_radians):
    a = np.asarray(axis, float)
    if a.shape != (3,) or not np.isfinite(a).all() or np.linalg.norm(a)<1e-9:
        raise ValueError("Need a finite nonzero 3D axis")
    a /= np.linalg.norm(a)
    x,y,z = a; k = np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
    return np.eye(3) + np.sin(angle_radians)*k + (1-np.cos(angle_radians))*(k@k)


def turntable_pose(angle_deg, center_m, axis):
    """Return T_world_from_camera for a rotating object and a physically fixed camera.

    World is the camera-coordinate frame at object angle zero. G maps the
    angle-zero object into its current camera pose; this returns inverse(G).
    """
    center = np.asarray(center_m, float)
    if center.shape != (3,) or not np.isfinite(center).all() or not np.isfinite(angle_deg):
        raise ValueError("Invalid angle or turntable center")
    r = rotation_axis_angle(axis, np.deg2rad(angle_deg))
    g = np.eye(4); g[:3,:3] = r; g[:3,3] = center-r@center
    return np.linalg.inv(g)


def fit_axis_circle(points, preferred_axis=(0.,-1.,0.)):
    """Fit an off-axis target's circular orbit. Input measurements are meters."""
    p = np.asarray(points, float)
    if p.ndim!=2 or p.shape[1]!=3 or len(p)<6 or not np.isfinite(p).all():
        raise ValueError("At least six finite XYZ orbit samples are required")
    mean = p.mean(axis=0); _, s, vh = np.linalg.svd(p-mean, full_matrices=False)
    if s[1] < 1e-4 or s[1]/s[0] < 0.15:
        raise ValueError("Orbit samples are collinear / cover too small an arc")
    xy = (p-mean) @ vh[:2].T
    a = np.column_stack((2*xy, np.ones(len(xy))))
    sol, *_ = np.linalg.lstsq(a, np.sum(xy*xy,axis=1), rcond=None)
    radius2 = sol[2] + sol[0]**2 + sol[1]**2
    if radius2 <= 0:
        raise ValueError("Invalid circle fit")
    center = mean + sol[:2] @ vh[:2]
    axis = vh[2]
    pref = np.asarray(preferred_axis,float)
    if pref.shape!=(3,) or np.linalg.norm(pref)<1e-9:
        raise ValueError("Preferred axis must be nonzero XYZ")
    if axis@pref < 0: axis = -axis
    v = p-center
    radial = np.linalg.norm(v-(v@axis)[:,None]*axis,axis=1)
    residual = np.sqrt((radial-np.sqrt(radius2))**2 + (v@axis)**2)
    angles = np.mod(np.arctan2(xy[:,1]-sol[1],xy[:,0]-sol[0]),2*np.pi)
    gaps = np.diff(np.r_[np.sort(angles), np.sort(angles)[0]+2*np.pi])
    coverage = np.rad2deg(2*np.pi-gaps.max())
    return {"center_m":center.tolist(), "axis":axis.tolist(), "radius_m":float(np.sqrt(radius2)),
            "rms_residual_mm":float(np.sqrt(np.mean(residual**2))*1000),
            "observed_arc_deg":float(coverage), "sample_count":len(p),
            "warning":"Fitted from depth measurements; independently verify axis and rotation sign."}


def voxel_average(points, voxel_m):
    p = np.asarray(points,float)
    p = p[np.isfinite(p).all(axis=1)]
    if voxel_m <= 0: raise ValueError("voxel_m must be positive")
    if not len(p): return p
    key = np.floor(p/voxel_m).astype(np.int64)
    _, inverse, count = np.unique(key,axis=0,return_inverse=True,return_counts=True)
    sums = np.zeros((len(count),3)); np.add.at(sums,inverse,p)
    return sums/count[:,None]


def measurement_report(points, scope="observed_surfaces_only"):
    p = np.asarray(points,float)
    if p.ndim!=2 or p.shape[1]!=3: raise ValueError("Expected Nx3 points")
    p = p[np.isfinite(p).all(axis=1)]
    if len(p)<3: raise ValueError("Too few valid points for measurement")
    lo,hi = p.min(axis=0),p.max(axis=0)
    qlo,qhi = np.percentile(p,[1,99],axis=0)
    mean = p.mean(axis=0)
    _,_,vh = np.linalg.svd(p-mean, full_matrices=False)
    axes = vh.T
    if np.linalg.det(axes)<0: axes[:,2] *= -1
    local = (p-mean)@axes
    return {"units":"meters", "point_count":int(len(p)), "scope":scope,
            "coordinate_frame":"X right, Y down, Z forward; reference camera at scan start",
            "aabb_min_m":lo.tolist(), "aabb_max_m":hi.tolist(), "aabb_extent_mm":((hi-lo)*1000).tolist(),
            "percentile_1_99_extent_mm":((qhi-qlo)*1000).tolist(),
            "pca_obb_extent_mm":(np.ptp(local,axis=0)*1000).tolist(),
            "pca_axes_columns":axes.tolist(),
            "warnings":["These are sampled-surface extents, not certified product dimensions.",
                        "Percentile extents deliberately discard outer samples and can understate size.",
                        "PCA axes are data-dependent; they are not necessarily engineering L/W/H.",
                        "No complete-object volume is inferred from an open or incomplete scan."]}
`````

---

<a id="source-file-13"></a>
## `src/kinectscan/reconstruct.py`

`````python
"""Reuse Open3D ICP/pose graphs/TSDF rather than implement a fusion engine."""
from __future__ import annotations
import numpy as np
from .geometry import depth_to_xyz, transform_points, voxel_average, measurement_report, validate_transform
from .storage import load_session, load_frame, write_json, export_geometry, new_directory


def open3d_module():
    try: import open3d as o3d
    except ImportError as exc:
        raise RuntimeError("Open3D is required for reconstruction/viewing. Use the documented Ubuntu Python 3.10-3.12 environment and requirements-ubuntu.txt.") from exc
    return o3d


def _cloud(o3d,depth,k,voxel):
    points=depth_to_xyz(depth,k).reshape(-1,3)
    points=points[np.isfinite(points).all(axis=1)]
    cloud=o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    cloud=cloud.voxel_down_sample(voxel)
    if len(cloud.points)<100: raise ValueError("Too few segmented points for registration")
    cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel*4,max_nn=40))
    cloud.orient_normals_towards_camera_location(np.zeros(3))
    return cloud


def _icp(o3d,source,target,voxel,initial):
    transform=np.array(initial,copy=True)
    reg=o3d.pipelines.registration
    for factor,iterations in ((4,60),(2,40),(1,30)):
        size=voxel*factor
        src=source.voxel_down_sample(size); dst=target.voxel_down_sample(size)
        src.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=size*4,max_nn=40))
        dst.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=size*4,max_nn=40))
        result=reg.registration_icp(src,dst,size*3,transform,
              reg.TransformationEstimationPointToPlane(),
              reg.ICPConvergenceCriteria(max_iteration=iterations))
        transform=validate_transform(result.transformation)
    return result


def _quality(result):
    t=validate_transform(result.transformation)
    angle=float(np.degrees(np.arccos(np.clip((np.trace(t[:3,:3])-1)/2,-1,1))))
    return {"fitness":float(result.fitness),"inlier_rmse_m":float(result.inlier_rmse),
            "rotation_deg":angle,"translation_m":float(np.linalg.norm(t[:3,3]))}


def reconstruct(session,out,mode,*,voxel_m=0.006,min_fitness=0.6,max_rmse_m=0.02,
                max_rotation_deg=25.,max_translation_m=0.30,close_loop=False):
    if mode not in ("known","auto","static"): raise ValueError("Invalid reconstruction mode")
    if not 0.001<=voxel_m<=0.05: raise ValueError("voxel_m must be 0.001..0.05")
    if not 0<min_fitness<=1 or max_rmse_m<=0: raise ValueError("Invalid registration thresholds")
    if close_loop and mode!="auto": raise ValueError("Loop closure applies only to auto mode")
    manifest,entries=load_session(session)
    if mode=="static" and manifest.get("subject_motion")!="stationary":
        raise ValueError("Static integration requires a recording explicitly marked stationary. Rotating people/objects cannot use identity poses.")
    if mode=="auto" and not manifest.get("foreground_isolated",False):
        raise ValueError("Auto mode requires ROI, 3D crop, or background isolation at capture time. Never register a rotating subject together with a stationary room.")
    if len(entries)>1200: raise ValueError("Session exceeds 1200-frame safety limit; split or subsample the recording")
    o3d=open3d_module(); out=new_directory(out)
    records=[]; poses=[]; clouds=[]; quality=[]; k0=None
    for i,(path,item) in enumerate(entries):
        depth,k,pose=load_frame(path)
        if k.distortion and not np.allclose(k.distortion,0):
            raise ValueError("Session depth must be rectified before TSDF integration")
        if k0 is None: k0=k
        if (k.width,k.height)!=(k0.width,k0.height) or not np.allclose(k.matrix,k0.matrix):
            raise ValueError("Mixed intrinsics in one session are unsupported")
        records.append((path,item))
        if mode=="known":
            if pose is None: raise ValueError(f"Known-pose mode requires T_world_from_camera in {path}")
            poses.append(pose)
        elif mode=="static": poses.append(np.eye(4))
        else:
            current=_cloud(o3d,depth,k,voxel_m)
            if i==0:
                poses.append(np.eye(4)); clouds.append(current); continue
            # Current camera-coordinate object cloud -> previous cloud.
            result=_icp(o3d,current,clouds[-1],voxel_m,np.eye(4))
            q=_quality(result); q["frame_index"]=i; quality.append(q)
            bad=(q["fitness"]<min_fitness or q["inlier_rmse_m"]>max_rmse_m or
                 q["rotation_deg"]>max_rotation_deg or q["translation_m"]>max_translation_m)
            if bad:
                write_json(out/"registration_failure.json",{"failed_frame":str(path),"quality":q,
                    "message":"Stopped before integration; no questionable frame was silently fused.",
                    "advice":"Slow rotation / denser captures / isolate subject / verify geometry. Thresholds do not prove accuracy."})
                raise RuntimeError(f"Registration rejected frame {i}: {q}. See registration_failure.json")
            poses.append(poses[-1]@result.transformation); clouds.append(current)
    if mode=="auto" and close_loop:
        if len(clouds)<10: raise ValueError("Loop closure requires at least 10 views and an actual return to the start pose")
        result=_icp(o3d,clouds[-1],clouds[0],voxel_m,poses[-1])
        q=_quality(result); q["edge"]="last_to_first"
        # Endpoint must physically overlap first view; a good local metric alone is not proof.
        if q["fitness"]<max(min_fitness,0.7) or q["inlier_rmse_m"]>max_rmse_m:
            write_json(out/"loop_failure.json",q)
            raise RuntimeError("Requested loop closure did not pass overlap/RMSE gates")
        reg=o3d.pipelines.registration; graph=reg.PoseGraph()
        for pose in poses: graph.nodes.append(reg.PoseGraphNode(pose))
        for i in range(1,len(poses)):
            rel=np.linalg.inv(poses[i-1])@poses[i]
            info=reg.get_information_matrix_from_point_clouds(clouds[i],clouds[i-1],voxel_m*3,rel)
            graph.edges.append(reg.PoseGraphEdge(i,i-1,rel,info,uncertain=False))
        info=reg.get_information_matrix_from_point_clouds(clouds[-1],clouds[0],voxel_m*3,result.transformation)
        graph.edges.append(reg.PoseGraphEdge(len(poses)-1,0,result.transformation,info,uncertain=True))
        reg.global_optimization(graph,reg.GlobalOptimizationLevenbergMarquardt(),
             reg.GlobalOptimizationConvergenceCriteria(),
             reg.GlobalOptimizationOption(max_correspondence_distance=voxel_m*3,
                                          edge_prune_threshold=0.25,reference_node=0))
        poses=[validate_transform(node.pose) for node in graph.nodes]; quality.append(q)
    volume=o3d.pipelines.integration.ScalableTSDFVolume(voxel_length=voxel_m,
            sdf_trunc=voxel_m*4,color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor,
            depth_sampling_stride=1)
    intrinsic=o3d.camera.PinholeCameraIntrinsic(k0.width,k0.height,k0.fx,k0.fy,k0.cx,k0.cy)
    dummy=o3d.geometry.Image(np.zeros((k0.height,k0.width,3),dtype=np.uint8))
    for (path,item),pose in zip(records,poses):
        depth,_,_=load_frame(path)
        rgbd=o3d.geometry.RGBDImage.create_from_color_and_depth(dummy,o3d.geometry.Image(depth),
              depth_scale=1000.,depth_trunc=9.9,convert_rgb_to_intensity=False)
        # Open3D integrates WORLD -> CAMERA, inverse of the stored pose.
        volume.integrate(rgbd,intrinsic,np.linalg.inv(pose))
    mesh=volume.extract_triangle_mesh()
    mesh.remove_degenerate_triangles(); mesh.remove_duplicated_triangles()
    mesh.remove_unreferenced_vertices(); mesh.compute_vertex_normals()
    vertices=np.asarray(mesh.vertices); triangles=np.asarray(mesh.triangles)
    if len(vertices)<3 or len(triangles)<1: raise RuntimeError("No surface reconstructed; inspect depth masks, scale, poses and voxel size")
    fused=volume.extract_point_cloud(); points=np.asarray(fused.points)
    if len(points)<3: points=vertices
    export_geometry(out,points,vertices,triangles,prefix="fused")
    report=measurement_report(points,"multi_view_observed_surface; coverage_not_certified")
    report.update({"mode":mode,"frames_integrated":len(poses),"voxel_m":voxel_m,
                   "closed_surface_check_performed":False,
                   "print_readiness":"Not guaranteed. Inspect holes, self-intersections, units and boundaries before printing.",
                   "color":"geometry_only; no RGB registration or texture atlas"})
    write_json(out/"measurements.json",report)
    write_json(out/"poses.json",{"convention":"T_world_from_camera; meters; world=first-view camera frame",
        "frames":[{"path":item["path"],"T_world_from_camera":p.tolist()} for (_,item),p in zip(records,poses)]})
    write_json(out/"quality.json",{"registration":quality,
         "warning":"Low ICP residual and a closed mesh do not establish metric accuracy or unseen-surface coverage."})
    return report


def fuse_known_clouds(session,out,voxel_m=0.005):
    """Dependency-light known-pose point fusion, with no inferred mesh."""
    manifest,entries=load_session(session); clouds=[]
    for path,item in entries:
        depth,k,pose=load_frame(path)
        if pose is None: raise ValueError("Every frame must contain a known relative pose")
        p=depth_to_xyz(depth,k).reshape(-1,3); p=p[np.isfinite(p).all(axis=1)]
        clouds.append(transform_points(p,pose))
    if not clouds: raise ValueError("No input frames")
    points=voxel_average(np.concatenate(clouds),voxel_m)
    out=new_directory(out); export_geometry(out,points,prefix="fused_known")
    report=measurement_report(points,"known_pose_multi_view_samples; coverage_not_certified")
    write_json(out/"measurements.json",report)
    return report
`````

---

<a id="source-file-14"></a>
## `src/kinectscan/storage.py`

`````python
"""Local-only records and explicit geometry formats/units. No pickle loading."""
from __future__ import annotations
import json
import os
from pathlib import Path
import struct
import numpy as np
from .geometry import Intrinsics, validate_depth, validate_transform


def write_json(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+".tmp")
    temp.write_text(json.dumps(data,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    os.replace(temp,path)


def new_directory(path):
    p=Path(path)
    if p.exists() and any(p.iterdir()):
        raise FileExistsError(f"Refusing to overwrite nonempty output directory: {p}")
    p.mkdir(parents=True,exist_ok=True)
    return p


def save_frame(path,depth,k,*,raw=None,timestamp=0,host_time=0.,pose=None):
    validate_depth(depth,k)
    arrays={"depth_mm":depth,"intrinsics_json":np.array(json.dumps(k.to_dict())),
            "device_timestamp":np.array(timestamp,dtype=np.uint32),
            "host_monotonic_s":np.array(host_time,dtype=float)}
    if raw is not None: arrays["raw_depth_mm"]=validate_depth(raw,k)
    if pose is not None: arrays["T_world_from_camera"]=validate_transform(pose)
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+".tmp")
    with temp.open("wb") as f: np.savez_compressed(f,**arrays)
    os.replace(temp,path)


def load_frame(path):
    with np.load(path,allow_pickle=False) as data:
        k=Intrinsics.from_dict(json.loads(str(data["intrinsics_json"].item())))
        depth=validate_depth(data["depth_mm"],k).copy()
        pose=validate_transform(data["T_world_from_camera"]).copy() if "T_world_from_camera" in data else None
        return depth,k,pose


def load_session(path):
    root=Path(path)
    manifest=json.loads((root/"session.json").read_text())
    if manifest.get("schema_version")!=1: raise ValueError("Unsupported session schema")
    frames=[]
    for item in manifest["frames"]:
        p=(root/item["path"]).resolve()
        if root.resolve() not in p.parents: raise ValueError("Unsafe frame path in manifest")
        if not p.is_file(): raise FileNotFoundError(p)
        frames.append((p,item))
    if not frames: raise ValueError("Session contains no frames")
    return manifest,frames


def _points(points):
    p=np.asarray(points,float)
    if p.ndim!=2 or p.shape[1]!=3 or not len(p) or not np.isfinite(p).all():
        raise ValueError("Need a nonempty finite Nx3 point array")
    return p


def write_cloud(path,points):
    p=_points(points); path=Path(path); ext=path.suffix.lower()
    if ext==".xyz":
        np.savetxt(path,p,fmt="%.9f",header="units=meters; X right Y down Z forward")
    elif ext==".ply":
        header=(f"ply\nformat ascii 1.0\ncomment units meters\nelement vertex {len(p)}\n"
                "property double x\nproperty double y\nproperty double z\nend_header\n")
        with path.open("w") as f:
            f.write(header); np.savetxt(f,p,fmt="%.9f")
    elif ext==".pcd":
        header=("# .PCD v0.7; units meters\nVERSION 0.7\nFIELDS x y z\nSIZE 8 8 8\nTYPE F F F\n"
                f"COUNT 1 1 1\nWIDTH {len(p)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(p)}\nDATA ascii\n")
        with path.open("w") as f:
            f.write(header); np.savetxt(f,p,fmt="%.9f")
    else: raise ValueError("Point cloud format must be PLY, PCD, or XYZ")


def write_mesh(path,vertices,triangles,*,stl_units="mm"):
    v=_points(vertices); t=np.asarray(triangles,dtype=np.int64)
    if t.ndim!=2 or t.shape[1]!=3 or not len(t) or t.min()<0 or t.max()>=len(v):
        raise ValueError("Need valid nonempty triangle indices")
    path=Path(path); ext=path.suffix.lower()
    if ext==".obj":
        with path.open("w") as f:
            f.write("# units meters; geometry only; no texture\n")
            np.savetxt(f,v,fmt="v %.9f %.9f %.9f")
            np.savetxt(f,t+1,fmt="f %d %d %d")
    elif ext==".ply":
        with path.open("w") as f:
            f.write(f"ply\nformat ascii 1.0\ncomment units meters\nelement vertex {len(v)}\n"
                    "property double x\nproperty double y\nproperty double z\n"
                    f"element face {len(t)}\nproperty list uchar int vertex_indices\nend_header\n")
            np.savetxt(f,v,fmt="%.9f")
            np.savetxt(f,np.column_stack((np.full(len(t),3),t)),fmt="%d")
    elif ext==".stl":
        if stl_units not in ("m","mm"): raise ValueError("STL units must be m or mm")
        vv=v*(1000. if stl_units=="mm" else 1.)
        p=vv[t]; n=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0])
        norm=np.linalg.norm(n,axis=1); n/=np.maximum(norm[:,None],1e-20)
        records=np.zeros(len(t),dtype=np.dtype([("normal","<f4",(3,)),("vertices","<f4",(3,3)),("attr","<u2")]))
        records["normal"]=n; records["vertices"]=p
        with path.open("wb") as f:
            f.write(f"KinectScan coordinates in {stl_units}; units require importer agreement".encode("ascii")[:80].ljust(80,b" "))
            f.write(struct.pack("<I",len(t))); f.write(records.tobytes())
        write_json(path.with_suffix(".stl.units.json"),{"coordinate_units":stl_units,
            "meters_per_unit":0.001 if stl_units=="mm" else 1.,
            "warning":"STL has no standard unit declaration. Select these units in the receiving application."})
    else: raise ValueError("Mesh format must be PLY, OBJ, or STL")


def export_geometry(out,points,vertices=None,triangles=None,prefix="observed"):
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    for ext in ("ply","pcd","xyz"): write_cloud(out/f"{prefix}_points.{ext}",points)
    if vertices is not None and len(vertices) and triangles is not None and len(triangles):
        for ext in ("ply","obj","stl"):
            write_mesh(out/f"{prefix}_mesh.{ext}",vertices,triangles)
`````

---

<a id="source-file-15"></a>
## `src/kinectscan/synthetic.py`

`````python
"""Analytical box raycasts for tests. These are not Kinect measurements."""
from __future__ import annotations
import numpy as np
from .geometry import Intrinsics, turntable_pose, transform_points, depth_to_xyz, grid_mesh, measurement_report
from .storage import new_directory, save_frame, write_json, export_geometry


def raycast_boxes(k,pose,boxes):
    v,u=np.indices((k.height,k.width),dtype=float)
    rays=np.stack(((u-k.cx)/k.fx,(v-k.cy)/k.fy,np.ones_like(u)),axis=-1)
    direction=rays@pose[:3,:3].T; origin=pose[:3,3]
    best=np.full((k.height,k.width),np.inf)
    for lo,hi in boxes:
        lo=np.asarray(lo); hi=np.asarray(hi)
        parallel=np.abs(direction)<1e-12
        safe=np.where(parallel,1.,direction)
        ta=(lo-origin)/safe; tb=(hi-origin)/safe
        near=np.minimum(ta,tb); far=np.maximum(ta,tb)
        outside=parallel & ((origin<lo)|(origin>hi))
        near=np.where(parallel,-np.inf,near); far=np.where(parallel,np.inf,far)
        enter=near.max(axis=-1); leave=far.min(axis=-1)
        hit=(leave>=np.maximum(enter,0)) & ~outside.any(axis=-1)
        distance=np.where(enter>0,enter,leave)
        best=np.minimum(best,np.where(hit & (distance>0),distance,np.inf))
    depth=np.zeros(best.shape,dtype=np.uint16)
    good=np.isfinite(best)&(best<9.9)
    depth[good]=np.rint(best[good]*1000).astype(np.uint16)
    return depth


def create_demo(out,step_deg=10):
    if not 1<=step_deg<=45 or 360%step_deg:
        raise ValueError("Synthetic step must divide 360 and be between 1 and 45 degrees")
    out=new_directory(out); frames=out/"frames"; frames.mkdir()
    k=Intrinsics(160,120,150,150,79.5,59.5,source="synthetic analytic camera; not a Kinect calibration")
    center=[0,0,1.25]; axis=[0,-1,0]
    boxes=[([-0.20,-0.15,1.15],[0.20,0.15,1.35]),
           ([0.06,-0.25,1.18],[0.15,-0.15,1.28])]
    manifest={"schema_version":1,"synthetic":True,"subject_motion":"known_turntable",
              "foreground_isolated":True,"intrinsics":k.to_dict(),"frames":[],
              "truth":{"aabb_extent_mm":[400,400,200],"center_m":center,"axis":axis},
              "warning":"Synthetic data only. This demonstrates processing, not hardware compatibility or sensor accuracy."}
    first=None
    for i,angle in enumerate(range(0,361,step_deg)):
        pose=turntable_pose(angle,center,axis); depth=raycast_boxes(k,pose,boxes)
        rel=f"frames/{i:06d}.npz"; save_frame(out/rel,depth,k,timestamp=i*100,host_time=i*.1,pose=pose)
        manifest["frames"].append({"path":rel,"angle_deg":angle,"sample_index":i})
        if first is None: first=depth
    write_json(out/"session.json",manifest)
    obs=out/"first_view_observed"; obs.mkdir()
    xyz=depth_to_xyz(first,k).reshape(-1,3); xyz=xyz[np.isfinite(xyz).all(axis=1)]
    vertices,triangles=grid_mesh(first,k,stride=1,max_edge_m=.04)
    export_geometry(obs,xyz,vertices,triangles,prefix="synthetic_observed")
    write_json(obs/"measurements.json",measurement_report(xyz,"synthetic_single_view_only"))
    return manifest
`````

---

<a id="source-file-16"></a>
## `tests/test_capture_binding.py`

`````python
import ctypes as ct
import numpy as np
from kinectscan import capture

class Fn:
    def __init__(self,f): self.f=f
    def __call__(self,*args): return self.f(*args)

class FakeLib:
    def __init__(self):
        self.data=np.full((480,640),1234,np.uint16)
        self.data[0,0]=10000
        self.freenect_sync_get_depth=Fn(self.read)
        self.freenect_sync_stop=Fn(lambda: None)
        self.freenect_sync_camera_to_world=Fn(self.project)
    def read(self,ptr,stamp,index,fmt):
        assert fmt==5
        ct.cast(ptr,ct.POINTER(ct.c_void_p))[0]=self.data.ctypes.data
        ct.cast(stamp,ct.POINTER(ct.c_uint32))[0]=77
        return 0
    def project(self,u,v,z,x,y,index):
        ct.cast(x,ct.POINTER(ct.c_double))[0]=(u-320)*z/580.
        ct.cast(y,ct.POINTER(ct.c_double))[0]=(v-240)*z/581.
        return 0

def test_native_binding_copy_and_factory_intrinsics(monkeypatch):
    fake=FakeLib()
    monkeypatch.setattr(capture,'library_path',lambda:'fake')
    monkeypatch.setattr(capture.ct,'CDLL',lambda name:fake)
    device=capture._Native(0)
    depth,stamp=device.read()
    assert stamp==77 and depth[0,0]==0
    fake.data[1,1]=900
    assert depth[1,1]==1234
    k=device.intrinsics()
    assert np.allclose([k.fx,k.fy,k.cx,k.cy],[580,581,320,240])

def test_missing_library(monkeypatch):
    monkeypatch.setattr(capture,'library_path',lambda:None)
    import pytest
    with pytest.raises(RuntimeError,match='not found'): capture._Native(0)
`````

---

<a id="source-file-17"></a>
## `tests/test_geometry.py`

`````python
import numpy as np
import pytest
from kinectscan.geometry import (Intrinsics, depth_to_xyz, median_depth, segment_depth,
    grid_mesh, transform_points, turntable_pose, rotation_axis_angle,
    fit_axis_circle, validate_transform, voxel_average, measurement_report)

@pytest.fixture
def k():
    return Intrinsics(8,6,100,100,3.5,2.5,source="test")

def test_projection_units(k):
    d=np.full((6,8),1000,np.uint16)
    p=depth_to_xyz(d,k)
    assert np.allclose(p[2,3],[-.005,-.005,1.])
    assert np.isclose(np.linalg.norm(p[2,3]-p[2,4]),.01)

@pytest.mark.parametrize("value",[0,10000,65535])
def test_invalid_depth_is_not_origin(k,value):
    d=np.full((6,8),value,np.uint16)
    assert np.isnan(depth_to_xyz(d,k)).all()

@pytest.mark.parametrize("fx",[0,-1,float('nan'),float('inf')])
def test_intrinsics_validation(fx):
    with pytest.raises(ValueError): Intrinsics(640,480,fx,580,320,240)

def test_depth_shape_type(k):
    with pytest.raises(ValueError): depth_to_xyz(np.ones((6,8)),k)
    with pytest.raises(ValueError): depth_to_xyz(np.ones((8,6),np.uint16),k)

def test_median_missing_values():
    frames=[np.array([[1000,0],[1000,1000]],np.uint16),
            np.array([[1002,0],[0,1300]],np.uint16),
            np.array([[998,1000],[1000,700]],np.uint16)]
    out=median_depth(frames,max_std_mm=10)
    assert out.tolist()==[[1000,0],[0,0]]

def test_segmentation_signed_background(k):
    d=np.full((6,8),1000,np.uint16); bg=np.full_like(d,900)
    assert not segment_depth(d,k,background=bg).any()
    bg[:]=1100; bg[0,0]=0
    out=segment_depth(d,k,background=bg)
    assert out[0,0]==0 and np.count_nonzero(out)==47

def test_roi_and_box(k):
    d=np.full((6,8),1000,np.uint16)
    out=segment_depth(d,k,roi=[2,1,6,5],box=[-.02,.02,-.02,.02,.8,1.2])
    assert np.count_nonzero(out)==16

def test_bad_roi_and_range(k):
    d=np.full((6,8),1000,np.uint16)
    with pytest.raises(ValueError): segment_depth(d,k,roi=[-1,0,4,5])
    with pytest.raises(ValueError): segment_depth(d,k,z_min=2,z_max=1)

def test_largest_component(k):
    d=np.zeros((6,8),np.uint16); d[:2,:2]=1000; d[4,6]=1000
    out=segment_depth(d,k,largest_component=True)
    assert np.count_nonzero(out)==4

def test_grid_mesh_plane(k):
    d=np.full((6,8),1000,np.uint16)
    v,t=grid_mesh(d,k,stride=1,max_edge_m=.02)
    assert len(v)==48 and len(t)==70
    normals=np.cross(v[t[:,1]]-v[t[:,0]],v[t[:,2]]-v[t[:,0]])
    assert (normals[:,2]<0).all()

def test_grid_mesh_does_not_bridge_step(k):
    d=np.full((6,8),1000,np.uint16); d[:,4:]=2000
    v,t=grid_mesh(d,k,stride=1,max_edge_m=.04)
    assert np.all(np.ptp(v[t][:,:,2],axis=1)==0)

def test_grid_mesh_does_not_fill_invalid(k):
    d=np.full((6,8),1000,np.uint16); d[:,3:5]=0
    v,t=grid_mesh(d,k,stride=1,max_edge_m=1.)
    assert len(t)>0
    assert (np.ptp(v[t][:,:,0],axis=1)<.02).all()

def test_turntable_inverse_transform():
    c=np.array([.02,.1,1.3]); axis=[0,-1,0]; angle=43
    r=rotation_axis_angle(axis,np.deg2rad(angle))
    original=np.array([[.12,.1,1.25],[-.2,0,1.4]])
    rotated=(original-c)@r.T+c
    assert np.allclose(transform_points(rotated,turntable_pose(angle,c,axis)),original)
    assert np.allclose(turntable_pose(360,c,axis),np.eye(4))

def test_transform_rejects_scale_and_reflection():
    t=np.eye(4); t[0,0]=2
    with pytest.raises(ValueError): validate_transform(t)
    t[0,0]=-1
    with pytest.raises(ValueError): validate_transform(t)

def test_axis_fit():
    theta=np.linspace(0,2*np.pi,12,endpoint=False)
    center=np.array([.1,.2,1.4])
    p=center+np.column_stack((.1*np.cos(theta),np.zeros(12),.1*np.sin(theta)))
    result=fit_axis_circle(p)
    assert np.allclose(result['center_m'],center)
    assert np.allclose(result['axis'],[0,-1,0])
    assert result['rms_residual_mm']<1e-6
    assert result['observed_arc_deg']>=329.9

def test_axis_fit_rejects_line():
    with pytest.raises(ValueError): fit_axis_circle(np.column_stack((np.arange(6),np.zeros(6),np.ones(6))))

def test_voxel_average():
    p=np.array([[.001,0,1],[.003,0,1],[-.001,0,1]])
    fused=voxel_average(p,.01)
    assert len(fused)==2
    assert np.allclose(np.sort(fused[:,0]),[-.001,.002])

def test_measurement_report_is_observed_only():
    p=np.array([[0,0,0],[.4,.3,.2],[.4,0,0],[0,.3,.2]])
    r=measurement_report(p)
    assert np.allclose(r['aabb_extent_mm'],[400,300,200])
    assert r['scope']=='observed_surfaces_only'
    assert 'volume' not in r
`````

---

<a id="source-file-18"></a>
## `tests/test_open3d_optional.py`

`````python
"""Executed only when Open3D is installed; absence must be reported, not hidden."""
import pytest
from kinectscan.synthetic import create_demo
from kinectscan.reconstruct import reconstruct


def test_open3d_known_pose_tsdf(tmp_path):
    pytest.importorskip('open3d',reason='Open3D unavailable: TSDF hardware-independent test not executed')
    create_demo(tmp_path/'session',step_deg=20)
    result=reconstruct(tmp_path/'session',tmp_path/'mesh','known',voxel_m=.008)
    assert result['frames_integrated']==19
    assert (tmp_path/'mesh/fused_mesh.stl').is_file()
    assert 350 < result['aabb_extent_mm'][0] < 450
`````

---

<a id="source-file-19"></a>
## `tests/test_storage_cli.py`

`````python
import json
from pathlib import Path
import struct
import numpy as np
import pytest
from kinectscan.geometry import Intrinsics
from kinectscan.storage import (save_frame,load_frame,write_mesh,write_cloud,new_directory,load_session,write_json)
from kinectscan.synthetic import create_demo
from kinectscan.reconstruct import fuse_known_clouds,reconstruct
from kinectscan.cli import main


def test_frame_roundtrip(tmp_path):
    k=Intrinsics(8,6,100,100,3.5,2.5)
    d=np.full((6,8),1200,np.uint16); p=tmp_path/'frame.npz'
    save_frame(p,d,k,raw=d,timestamp=123,pose=np.eye(4))
    dd,kk,pose=load_frame(p)
    assert np.array_equal(d,dd) and k==kk and np.allclose(pose,np.eye(4))

def test_stl_scale_and_binary_layout(tmp_path):
    v=np.array([[0.,0,0],[.1,0,0],[0,.2,0]]); t=np.array([[0,1,2]])
    p=tmp_path/'test.stl'; write_mesh(p,v,t)
    data=p.read_bytes()
    assert len(data)==134 and struct.unpack('<I',data[80:84])[0]==1
    values=struct.unpack('<12fH',data[84:])
    assert values[6]==100. and values[10]==200.
    assert json.loads(p.with_suffix('.stl.units.json').read_text())['coordinate_units']=='mm'

@pytest.mark.parametrize('ext',['ply','pcd','xyz'])
def test_cloud_exports(tmp_path,ext):
    p=tmp_path/f'cloud.{ext}'; write_cloud(p,np.array([[0,0,1],[1,2,3]]))
    assert 'meters' in p.read_text() and '3.000000000' in p.read_text()

@pytest.mark.parametrize('ext',['obj','ply'])
def test_mesh_exports(tmp_path,ext):
    p=tmp_path/f'mesh.{ext}'
    write_mesh(p,[[0,0,1],[.1,0,1],[0,.1,1]],[[0,1,2]])
    assert 'meters' in p.read_text()

def test_refuse_overwrite(tmp_path):
    (tmp_path/'existing').write_text('x')
    with pytest.raises(FileExistsError): new_directory(tmp_path)

def test_session_refuses_traversal(tmp_path):
    write_json(tmp_path/'session.json',{'schema_version':1,'frames':[{'path':'../secret.npz'}]})
    with pytest.raises(ValueError): load_session(tmp_path)

def test_synthetic_known_fusion(tmp_path):
    create_demo(tmp_path/'session',step_deg=20)
    report=fuse_known_clouds(tmp_path/'session',tmp_path/'out',.004)
    assert np.allclose(report['aabb_extent_mm'],[400,400,200],atol=15.)
    assert (tmp_path/'out'/'fused_known_points.ply').is_file()

def test_static_mode_refuses_rotating_scene_before_open3d_import(tmp_path):
    create_demo(tmp_path/'session',step_deg=20)
    with pytest.raises(ValueError,match='stationary'):
        reconstruct(tmp_path/'session',tmp_path/'out','static')

def test_snapshot_cli_without_hardware(tmp_path):
    create_demo(tmp_path/'session',step_deg=20)
    rc=main(['snapshot','--input',str(tmp_path/'session/frames/000000.npz'),
             '--out',str(tmp_path/'snapshot'),'--stride','1'])
    assert rc==0 and (tmp_path/'snapshot/observed_mesh.stl').is_file()
    rc=main(['measure','--input',str(tmp_path/'snapshot/frame.npz'),
             '--p1','75','60','--p2','85','60','--out',str(tmp_path/'distance.json')])
    assert rc==0
    assert json.loads((tmp_path/'distance.json').read_text())['distance_mm']>0

def test_invalid_measurement_fails(tmp_path):
    create_demo(tmp_path/'session',step_deg=20)
    assert main(['measure','--input',str(tmp_path/'session/frames/000000.npz'),
                 '--p1','0','0','--p2','1','1'])==2
`````
