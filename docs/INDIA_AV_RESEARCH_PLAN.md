# Autonomous vehicle research plan for Indian roads

Prepared 23 October 2026. Project: `india-av`. Status: all eight stories assigned and verified in the office task records. At dispatch verification, tasks 8–10 were running and 11–15 were queued under the three-task concurrency limit. Research results remain pending.

The objective is a real vehicle capable of safe automated driving in a precisely defined Indian operating environment. The first deliverable is a defensible feasibility decision and a simulation plan. Public-road operation is a later milestone with separate legal, engineering and operational gates. No deployment date or vehicle budget is established yet.

## Proposed first operating environment

Begin with a passenger-car research prototype on an access-controlled test track, in daylight and dry weather, on a mapped route. Use soft targets and exclude the public. Initially propose a 10 km/h upper ceiling, subject to measured braking distance, latency, surface friction and a qualified safety engineer's approval; this is not an established safe speed. Initial bench and vehicle checks may require a lower speed or no motion.

Specify entry and exit conditions for the operating design domain (ODD): geography, road geometry, speed, lighting, rain, visibility, traffic actors, sensor health and localization quality. Detect leaving that domain and execute a validated minimum-risk response. A safety driver does not by itself establish safety, legality or a Level 4 capability.

The operator shortlisted Bengaluru, Karnataka, and Chennai, Tamil Nadu for the initial location. Compare both before selecting a pilot city; neither has been selected or approved. Open operator decisions: passenger car versus another vehicle class; intended first customer and route; existing vehicle and documented actuation interfaces; funding and runway; access-controlled test site; available automotive, safety and legal specialists. Use these as unresolved inputs, not invented facts.

## Bengaluru and Chennai comparison

Maya and Ravi must produce a joint city decision table covering Karnataka and Tamil Nadu separately. Research the actual authorities and requirements for each proposed site and vehicle. Distinguish closed-track operation, human-driven recording and automated public-road operation. Do not infer permission from a startup policy, a demonstration by another company or a test facility's existence.

Compare documented access to controlled test sites, automotive engineering and testing partners, insurance, vehicle transport and recovery, staffing, facility cost, and the operator's practical access. Mark unconfirmed availability and pricing as unknown. Site safety and a defensible legal route are prerequisites, not factors that a low cost can outweigh.

Arjun and Omar must specify how to assess each candidate route's mixed traffic, two-wheelers, pedestrians, road geometry, surface condition, drainage, weather, visibility and localization. Zoe and Priya must assess Kannada/Tamil/English signage and operator communication needs against the actual site. Max and Lena must tag evidence by city, route, date and conditions, and prevent evaluation leakage between recordings. These are research questions; no comparative advantage or route suitability is assumed.

## Indian legal research baseline

The following is an initial statutory reading, not a project-specific legal clearance. Counsel must check current amendments, commencement notifications and state requirements before any physical testing.

| Provision | Initial reading |
| --- | --- |
| Motor Vehicles Act section 2B | Allows central-government exemptions for innovation and research subject to conditions. It is not an automatic research permit. |
| Sections 3 and 39 | Address driving licences and vehicle registration. Section 39 includes driving in places other than public places. |
| Section 52 | Restricts alterations that put registration particulars at variance with the manufacturer's original specification. |
| Section 110B | Establishes type approval, with specified exceptions including certain non-public testing and central exemptions. Eligibility requires verification. |
| Section 146 | Requires qualifying third-party insurance for public-place use, subject to the Act's exceptions. |

Source: [Motor Vehicles Act hosted by the Chhattisgarh Transport Department](https://cgtransport.gov.in/Notification/CMVA_1988.pdf), sections cited above. A private site is not a blanket exemption; classify the actual site and vehicle with counsel.

MoRTH's [24 July 2024 parliamentary answer](https://sansad.in/getFile/annex/265/AU269_afV4B6.pdf?source=pqars) describes prototype certification under CMVR rule 126. Obtain a written applicability assessment from a notified testing agency for the actual vehicle configuration; a production vehicle's existing approval cannot simply be assumed to cover research modifications.

The legal story must produce a dated matrix for:

- MoRTH exemption route, if needed; state transport authority and RTO responsibilities; traffic police and road-owner permissions for the proposed location. Distinguish each body's authority and avoid treating a local permission as a substitute for national requirements.
- Registration, modification, prototype/type-approval, temporary registration or trade-certificate applicability, vehicle category, fitness and commercial passenger/service permits where relevant. Check each suggested route against current text and eligibility.
- Insurance expressly covering the actual automated testing and modifications; third-party, employee/test-driver and product/public liability questions; exclusions, incident reporting and evidence preservation.
- Road-test versus closed-site versus passive recording requirements; landowner agreement, public access controls, emergency response and transport of the prototype to the site.
- Applicable criminal/civil liability, product safety and consumer claims; ownership of the vehicle, software and collected data; supplier warranties and contractual allocation of responsibility.
- Camera, plate, face, location and cabin data: processing basis, retention, access, security, children, vendors, transfers and data-subject handling. The DPDP Rules were notified in November 2025, with phased implementation; map each obligation's effective date from the Gazette rather than assuming everything commenced together. See [MeitY's rules and enforcement materials](https://www.meity.gov.in/documents/act-and-policies/digital-personal-data-protection-rules-2025-gDOxUjMtQWa?pageTitle=Digit) and [PIB notification overview](https://www.pib.gov.in/PressNoteDetails.aspx?ModuleId=3&NoteId=156054&lang=1&reg=3).
- Wireless/radio equipment approvals, imports, battery/electrical safety and cybersecurity requirements applicable to the selected equipment. Record applicability and evidence, not a generic list presented as law.

No general authorization for this project's public-road automated operation has been established. Finding neither a blanket ban nor an obvious permit is not permission. Draft questions for counsel, the transport department, a notified test agency and the insurer; external contact requires a separate instruction.

## Lessons from failures and evidence of progress

The controls below are proposed engineering responses to the evidence, not claims that another company's approach transfers directly to India.

| Case | Established finding | Proposed response and evidence |
| --- | --- | --- |
| Uber, Tempe, 2018 | NTSB found operator distraction, inadequate risk assessment and oversight, and an unsafe reliance on operator intervention; emergency collision-mitigation braking was precluded by the design. | Independent stopping safeguards; unknown-object and occlusion tests; operator monitoring and training; explicit stop-work authority. Demonstrate the response to a missed detection and an inattentive operator. |
| Cruise, California, 2023 | DMV suspended driverless testing and deployment permits, citing unsafe performance and safety-information misrepresentation among its grounds. | Preserve complete incident evidence, define prompt reporting and independent investigation, and validate post-contact stopping behavior. Never selectively present a successful part of a run. |
| GM's Cruise funding decision, 2024 | GM ended robotaxi development funding, citing the time and resources needed to scale and market competition. | Cost the entire service: attendants, remote assistance, recovery, maintenance, insurance, compute and site operations. Require funding for the next evidence milestone before expansion. |
| Tesla Autopilot investigation, 2024 closure report | NHTSA documented shortcomings in ensuring driver attention. This concerned supervised Level 2 assistance, not proof about every autonomous system. | Test mode confusion and foreseeable misuse; make automation limits and control ownership explicit; do not rely on a warning screen as the safety mechanism. |

Sources: [NTSB Tempe investigation](https://www.ntsb.gov/investigations/pages/hwy18mh010.aspx), [California DMV suspension statement](https://www.dmv.ca.gov/portal/news-and-media/dmv-statement-on-cruise-llc-suspension/), [GM announcement dated 10 December 2024](https://investor.gm.com/news-releases/news-release-details/gm-refocus-autonomous-driving-development-personal-vehicles/), [NHTSA investigation closure report](https://static.nhtsa.gov/odi/inv/2022/INCR-EA22002-14496.pdf).

Progress is possible within bounded conditions. [IIHS research published 23 July 2026](https://www.iihs.org/news/detail/waymos-driverless-cars-crash-less-often-than-people) found fewer police-reportable crashes per vehicle mile for Waymo in four US cities, while identifying reporting limitations. Treat that as evidence for studying bounded deployment and rigorous comparisons, not an Indian-road safety benchmark or a guarantee for our design.

## India-specific scenarios and technical research

Build a scenario catalogue covering two-wheelers filtering and cutting in, autorickshaws, buses hiding pedestrians, children emerging from occlusion, animals, wrong-way traffic, informal junction negotiation, unmarked lanes, roadworks, speed breakers, potholes, parked vehicles, emergency vehicles, police hand signals and regional signage. Include monsoon rain, spray, standing water, dust, glare, night lighting, obscured sensors, map changes and GNSS degradation. Conditions outside the initial ODD still require boundary-detection tests.

[IIIT Hyderabad's dataset catalogue](https://insaan.iiit.ac.in/datasets/) offers Indian-road, adverse-weather and two-wheeler research resources. Check each dataset's licence, provenance, commercial-use terms, class coverage and geographic/weather gaps. Split evaluation by route, recording session and conditions to prevent leakage. Dataset scores alone do not demonstrate closed-loop driving safety.

Research candidate modular stacks and simulators from their official documentation, including Autoware and CARLA, before choosing versions or downloading dependencies. Compare licensing, vehicle interfaces, compute needs, reproducibility, scenario coverage and maintenance. Do not assume this laptop can run the eventual workload. Compare camera-only and camera/radar/lidar options on measured ODD coverage, failure detection, cost and maintainability before procurement.

The architecture study must cover time synchronization and calibration; localization uncertainty; tracking and prediction; planning under uncertainty; deterministic actuation limits; independent watchdogs and stopping safeguards; power and communications faults; event logging; update rollback; and cybersecurity. General language-model output must not directly command steering, throttle or braking.

Use the scopes of [ISO 26262](https://www.iso.org/standard/68383.html), [ISO 21448](https://www.iso.org/standard/77490.html) and [ISO/SAE 21434](https://www.iso.org/standard/70918.html) to organize functional safety, intended-function limitations and cybersecurity research. Verify applicable editions and Indian adoption separately. A planning document is not certification, and the full standards may require licensed access.

## Milestones and exit evidence

| Gate | Work | Evidence required to proceed |
| --- | --- | --- |
| G0 Feasibility | ODD, legal route, failure analysis, cost and staffing | Operator selects use case and constraints; current legal unknowns have owners; no unsupported permission claims; initial hazard register and funding decision reviewed. |
| G1 Simulation | Reproducible baseline and Indian scenario suite | Locked software/data versions, seeds, expected behavior, coverage and regression results; quantitative acceptance thresholds justified before execution; unresolved critical failures block progression. |
| G2 Bench and hardware integration | Actuation and safety architecture, sensor calibration and fault injection | Qualified engineers review electrical/mechanical design; independently demonstrated stop/override and watchdog behavior; bounded latency and braking; legal/site/insurance readiness for the next test. |
| G3 Closed-track prototype | Low-speed supervised tests with controlled access | Approved test cards, soft targets, measured stopping envelope, operator drills, incident/recovery process and independently reviewed logs. Site permission and applicable legal obligations satisfied. |
| G4 Passive public-road recording | Human-driven recording only, if approved for the configuration | No actuation from research software; recording/privacy/installation permissions and insurance resolved; route and data handling approved. This gate may run earlier only after its own prerequisites. |
| G5 Restricted public-road automated pilot | Exact route, hours, weather, speed and operational staffing | Written legal basis and required authorizations; insurer confirmation; test-agency assessment; independent safety-case review; emergency coordination and operator approval. |
| G6 Expansion | One ODD dimension at a time | New hazard analysis, comparable exposure and incident evidence, regression coverage and renewed permissions where needed. |

The first research cycle is provisionally ten working days, not a vehicle launch commitment. Days 1–3: parallel legal, architecture, ODD and evidence work. Days 4–7: data, operator controls, observability, costs and traceability. Days 8–10: independent review and a go/no-go decision for simulation. Actual duration depends on staffing, quota and source access. No deadline automatically opens a gate.

Track collisions and contacts, safety interventions by cause, minimum separation, latency distributions and worst-case bounds, stop distance, localization error, sensor faults, ODD exits, route completion, recovery time and costs. Report exposure and confidence limits; zero incidents in a short demo and disengagement counts alone are insufficient safety evidence.

## Initial stories for every staff member

All stories are planning/research only. Verified task IDs: Maya 8, Ravi 9, Arjun 10, Priya 11, Zoe 12, Lena 13, Max 14, Omar 15. Each output needs primary-source links, source dates and effective dates where relevant, assumptions, unresolved questions, and pass/fail evidence against its acceptance criteria. Reports belong to the office project `india-av`; no unrelated repositories or company information are in scope.

The scheduler supports one prerequisite per task, so Omar's task depends on task 14. This does not guarantee every earlier task has finished. His brief requires all seven reports and an explicit failure for any unavailable or unfinished report; the manager must arrange a further review once missing work is complete. Assignment is not acceptance of any report or approval to start a physical test.

| ID | Owner | Story and output | Acceptance criteria | Dependencies |
| --- | --- | --- | --- | --- |
| IAV-001 | Maya | As project owner, I need a bounded use case and funded roadmap. Produce `01-charter-odd-budget.md`. | Define included/excluded ODD conditions and fallback; list operator decisions; compare Bengaluru and Chennai using the city criteria above and at least two feasible first use cases; provide cost categories and dated estimates or explicit unknowns; identify required human specialists, critical path and all gate owners. | None |
| IAV-002 | Ravi | As test sponsor, I need a verified Indian approval pathway. Produce `02-india-law-matrix.md`. | Cover every legal topic above with separate Karnataka/Bengaluru and Tamil Nadu/Chennai applicability; each row has provision, jurisdiction, effective date, authority, evidence and unanswered question; distinguish binding law, draft, guidance and inference; produce counsel/test-agency/insurer question packs; no unsupported lawful-to-test verdict. | None |
| IAV-003 | Arjun | As engineering lead, I need a fail-safe prototype architecture and build-versus-buy comparison. Produce `03-architecture-options.md`. | Trace hazards to sensing, planning, actuation and independent safeguards; compare stack/sensor/vehicle options with official sources; define timing and stop-distance budgets plus measurement plans; cover power, thermal, communications and cybersecurity faults; no vehicle modification or procurement. | None; reconcile with IAV-001 |
| IAV-004 | Priya | As project owner, I need failure lessons, a data policy and truthful operating documentation. Produce `04-lessons-data-operations.md`. | Verify the four cases above and add a supported commercial-failure case; separate findings from inference; map each lesson to a requirement/test; draft recording, retention and incident-reporting policies with legal questions; label capabilities accurately; no outreach or publication. | None; reconcile with IAV-002 |
| IAV-005 | Zoe | As safety operator, I need unambiguous modes and emergency procedures. Produce `05-operator-workflows.md`. | Specify manual, armed, active, degraded, stopping and locked-out states; control ownership, engagement checks, alarms and recovery; address attention failure and foreseeable misuse; walkthrough at least six abnormal situations; use sketches/specifications only. | None; reconcile with IAV-003 |
| IAV-006 | Lena | As test reviewer, I need a specification for traceable scenario results and replay. Produce `06-evidence-interface-spec.md`. | Define log schema, units, timestamps, software/data identifiers, intervention reasons, ODD state and evidence links; distinguish live from simulated data; specify stale/missing data and crash evidence handling; connect to operator flows; no live vehicle control or new hosted app. | None; reconcile with IAV-003 and IAV-005 |
| IAV-007 | Max | As researcher, I need a reproducible experiment contract and an honest local readiness audit. Produce `07-reproducibility-readiness.md`. | Read only this plan and relevant public tooling in adaptive-desktop; identify known versus unverified local simulation capabilities without starting services or hardware; specify version/seed/data/licence manifests and route-separated evaluation; create an India scenario checklist and evidence index; no other repos, code hosts, credentials or downloads. | None; reconcile with IAV-003 |
| IAV-008 | Omar | As independent reviewer, I need a safety and validation plan that can reject the design. Produce `08-hazards-validation.md`. | Create an initial hazard register covering at least 20 materially different hazards; include severity, exposure/controllability assumptions, mitigation, verification and owner; define simulation/bench/track fault tests and stopping rules; audit all outputs and legal overclaims; every critical unknown blocks the relevant physical gate. | Initial draft now; final review after IAV-001 through IAV-007 |

The manager verifies the plan, dispatches one bounded story per staff member, records actual task IDs and dependencies, and integrates the eight outputs into a readiness decision. The manager must not claim legal approval or engineering certification. A qualified human safety lead, automotive engineers, Indian counsel, the insurer and relevant authorities retain the real-world decisions.

## Completion of the first cycle

The research cycle is complete when all eight outputs are reviewed, every gate has an owner and evidence requirement, conflicts are resolved or explicitly blocked, and the operator receives a concise decision on whether to fund and begin simulation. Public-road testing, hardware changes, purchases, external messages and ongoing autonomous study are outside this cycle. Revisions remain within these eight stories; scope expansion returns to the operator.
