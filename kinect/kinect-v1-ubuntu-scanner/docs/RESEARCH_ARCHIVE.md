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
