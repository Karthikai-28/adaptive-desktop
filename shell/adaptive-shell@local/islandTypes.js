// Dynamic Island Types, Events, Priorities, and Constants
//
// Defines the unified event catalog, priority tiers, dwell durations,
// and state machine structures for the adaptive-desktop Dynamic Island.

/* exported IslandEvents, IslandPriority, IslandDwellMs, IslandActivityState, ActivityPrecedence */
/* global module */

var IslandEvents = {
    // Tier 1: Urgent (P1)
    QUOTA_CRITICAL_BREACH: 'QUOTA_CRITICAL_BREACH', // Claude quota <= 5%
    TASK_FAILED_ERROR:     'TASK_FAILED_ERROR',     // Agent task exited with error
    TIMER_EXPIRED:         'TIMER_EXPIRED',         // Focus timer reached 00:00

    // Tier 2: High (P2)
    QUOTA_CAUTION_BREACH:  'QUOTA_CAUTION_BREACH',  // Claude quota <= 20%
    TASK_COMPLETED_SUCCESS:'TASK_COMPLETED_SUCCESS',// Agent task completed successfully
    TIMER_DIGEST:          'TIMER_DIGEST',          // Focus stopped early: what arrived meanwhile

    // Tier 3: Normal (P3)
    TRACK_CHANGED:         'TRACK_CHANGED',         // Media track changed
    TASK_STARTED:          'TASK_STARTED',          // New background AI task launched
    TIMER_STARTED:         'TIMER_STARTED',         // Focus countdown initialized
    QUOTA_RESET_CONFIRMED: 'QUOTA_RESET_CONFIRMED', // Rate limit window refreshed

    // Tier 4: Ambient (P4)
    PLAYBACK_STATE_CHANGED:'PLAYBACK_STATE_CHANGED',// Play/pause toggle
    TASK_PROGRESS_UPDATE:  'TASK_PROGRESS_UPDATE',  // Milestone step / stdout update
    TIMER_TICK:            'TIMER_TICK',            // legacy name; ticks now update state directly
    TIMER_PAUSED:          'TIMER_PAUSED',          // Timer paused
    TIMER_RESUMED:         'TIMER_RESUMED',         // Timer resumed
    QUOTA_UPDATED:         'QUOTA_UPDATED',         // Routine quota / token count update
};

var IslandPriority = {
    P1_URGENT: 1,
    P2_HIGH: 2,
    P3_NORMAL: 3,
    P4_AMBIENT: 4,
};

var IslandDwellMs = {
    STICKY: -1,       // Remains until user interaction / dismissal
    P1_STICKY: -1,
    P2_CAUTION: 6000,
    P2_SUCCESS: 4000,
    P3_NORMAL: 3000,
    P4_AMBIENT: 2000,
};

var IslandActivityState = {
    IDLE: 'idle',
    COMPACT: 'compact',
    EXPANDED: 'expanded',
};

// Activity Precedence for multi-activity conflict resolution:
// When competing activities occur simultaneously (e.g. Media playing + Agent Task running):
// The higher rank takes the primary center pill; the secondary settles into the 32px satellite bubble.
var ActivityPrecedence = {
    TASK: 1,    // AI Task takes precedence in center pill
    TIMER: 2,   // Active timer takes second precedence
    MEDIA: 3,   // Media settles into satellite bubble when task/timer is active
    QUOTA: 4,   // Ambient quota indicators flank the clock
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        IslandEvents,
        IslandPriority,
        IslandDwellMs,
        IslandActivityState,
        ActivityPrecedence,
    };
}
