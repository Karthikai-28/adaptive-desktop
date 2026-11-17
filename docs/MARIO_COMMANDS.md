# Mario: what you can say

Say "Hey Mario" (or press Super+J), then any of these. Words in a different order
usually work too. This list is written from `services/mario-hub/commands.py`
(`python3 services/mario-hub/commands.py --markdown`); Mario Home shows it at
http://127.0.0.1:8791/commands, and "What can I say?" opens it.

## Start

| Say | What happens |
| --- | --- |
| Hey Mario … | Wake Mario by voice (after training it once in Mario Home), or press Super+J. |
| What can I say? | This list. |

## Kinect and you

| Say | What happens |
| --- | --- |
| How tall am I? / How tall are we? | Measures everyone in view with the Kinect, in cm: stand up straight 2-4 m away, facing it, all of you in view. |
| How many people are there? | Counts everyone in view and says who is standing, sitting or crouching. |
| How far am I from the TV? | Your distance from the Kinect, across the floor. |
| Open Kinect Studio | The camera, depth, 3D point cloud and sensors. |
| Tilt the Kinect down by 10 | Up or down, by any number of degrees (10 if you don't say). |
| Tilt the Kinect to minus 15 | To an angle from level, -27 to 27. |
| Level the Kinect | Back to straight ahead. |
| Night vision on / Switch to colour / Night vision auto | Infrared (sees in the dark), colour, or auto: colour while lit, infrared in the dark. |
| Use the Kinect as a webcam / Stop the Kinect webcam | "Kinect Camera" for Meet, Zoom, OBS. |
| Take a 3D snapshot | Saves the point cloud to Pictures/Kinect (PLY). |
| Turn the Kinect light red / Turn off the Kinect light | Green, red, yellow, blinking, off. |

## Hand gestures (Air)

| Say | What happens |
| --- | --- |
| Start gestures / Stop gestures | Hand control on or off (Super+G does the same). |
| Show the gesture demo | Scripted hands play every gesture. |

## TV

| Say | What happens |
| --- | --- |
| Connect to my TV | Mirrors this screen on the TV (Miracast). |
| Cast this window to the TV | Just the window you are in. |
| Stop casting / Disconnect | Back to the laptop alone. |
| Turn on the TV / Turn off the TV | Wakes it over the network; off works too. |
| TV volume up / Set the TV volume to 20 | Up, down, or a level 0-100. |
| Mute the TV / Unmute the TV |  |
| Show the clock on the TV | The wall page: clock, weather, vitals. |

## Apps and windows

| Say | What happens |
| --- | --- |
| Open Spotify / Open Files / Launch Firefox | Any app in the app grid, by its name. |
| Open YouTube / Open Gmail | Common sites open in the browser. |
| Switch to Chrome / Bring up Terminal | Brings that app's window to the front. |
| Spotify (an app's name on its own) | Opens it. A name misheard or said with an accent still finds its app. |
| Close this window / Close Spotify | The window you are in, or an app by name. |
| Maximise / Minimise | The window you are in. |
| Snap left / Put this window to the right | That half of the screen. |
| Go full screen |  |
| Centre the window |  |
| Move this window to the next desktop | Next or previous. |

## Desktops

| Say | What happens |
| --- | --- |
| Next desktop / Previous desktop |  |
| Go to desktop 2 | By number. |
| Show all windows | The overview. |
| Show all apps | The app grid. |
| Show the desktop | Hides every window; again brings them back. |
| Show my notifications / Open control center |  |
| Open the drop-down terminal / Open the palette |  |
| Lock the screen |  |

## Sound and music

| Say | What happens |
| --- | --- |
| Volume up / Turn the volume down / Louder | By 10%. |
| Set the volume to 40 | A level, in percent. |
| Mute / Unmute |  |
| Play / Pause / Next song / Previous song | Whatever is playing (Spotify, the browser, …). |

## More

| Say | What happens |
| --- | --- |
| Take a screenshot | Select an area, mark it up, copy or save it. |
| Do not disturb on / Turn off do not disturb | Notification banners off or on. |
| Search for weather in Bengaluru | A web search in the browser. |
| Go to github.com | Any address. |
| Add a task: call the plumber / Take a note: … | Into Mario's task list or notes. |
| Anything else | Mario answers (Claude, Gemini at Claude's limit). Code work becomes a plan you start with Run. |

## Hand gestures (with Air on)

See docs/AIR.md for the full list: raise an open palm to take control, pinch to
click, wave up or down to scroll, an L (thumb and index) opened or closed to zoom,
both hands pinching to zoom, a fist to grab a window (to the screen's edge: the next
desktop), a fast sideways swipe for the next desktop, two open palms apart for every
window.

