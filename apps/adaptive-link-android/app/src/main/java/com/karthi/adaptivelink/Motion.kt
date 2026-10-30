package com.karthi.adaptivelink

import androidx.compose.animation.AnimatedContentTransitionScope
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavBackStackEntry

/**
 * Material 3 motion for the phone shell: the emphasized easing curves,
 * screens that grow into place and slide back, things that give under the
 * finger, and the launch of a laptop app.
 */
internal object Motion {
    val Emphasized = CubicBezierEasing(.2f, 0f, 0f, 1f)
    val EmphasizedAccelerate = CubicBezierEasing(.3f, 0f, .8f, .15f)

    // Going in: the new screen grows from 92% and fades in over the old one.
    val enter: AnimatedContentTransitionScope<NavBackStackEntry>.() -> EnterTransition = {
        fadeIn(tween(300, 50, Emphasized)) + scaleIn(tween(400, easing = Emphasized), initialScale = .92f)
    }
    val exit: AnimatedContentTransitionScope<NavBackStackEntry>.() -> ExitTransition = {
        fadeOut(tween(150, easing = EmphasizedAccelerate))
    }
    // Coming back: the screen underneath slides in from the left, the one left behind slides away.
    val popEnter: AnimatedContentTransitionScope<NavBackStackEntry>.() -> EnterTransition = {
        fadeIn(tween(250, easing = Emphasized)) + slideInHorizontally(tween(350, easing = Emphasized)) { -it / 6 }
    }
    val popExit: AnimatedContentTransitionScope<NavBackStackEntry>.() -> ExitTransition = {
        fadeOut(tween(200, easing = EmphasizedAccelerate)) + slideOutHorizontally(tween(300, easing = EmphasizedAccelerate)) { it / 4 } +
            scaleOut(tween(300), targetScale = .96f)
    }
}

/** Clickable that gives under the finger with a spring, and ripples. */
@OptIn(ExperimentalFoundationApi::class)
internal fun Modifier.pressable(onLongClick: (() -> Unit)? = null, onClick: () -> Unit): Modifier = composed {
    val source = remember { MutableInteractionSource() }
    val pressed by source.collectIsPressedAsState()
    val scale by animateFloatAsState(if (pressed) .97f else 1f, spring(Spring.DampingRatioMediumBouncy, Spring.StiffnessMedium), label = "press")
    this.graphicsLayer { scaleX = scale; scaleY = scale }
        .combinedClickable(interactionSource = source, indication = ripple(), onLongClick = onLongClick, onClick = onClick)
}

/** A status dot that breathes: something is running. */
@Composable
internal fun PulseDot(color: Color, size: Int = 6) {
    val pulse = rememberInfiniteTransition(label = "pulse")
    val glow by pulse.animateFloat(1f, 2.4f, infiniteRepeatable(tween(1400, easing = FastOutSlowInEasing), RepeatMode.Restart), label = "glow")
    val fade by pulse.animateFloat(.55f, 0f, infiniteRepeatable(tween(1400, easing = FastOutSlowInEasing), RepeatMode.Restart), label = "fade")
    Box(Modifier.size((size * 2.4f).dp), contentAlignment = Alignment.Center) {
        Box(Modifier.size(size.dp).scale(glow).clip(CircleShape).background(color.copy(alpha = fade)))
        Box(Modifier.size(size.dp).clip(CircleShape).background(color))
    }
}

/**
 * Over the shell while a laptop app starts in the phone session: its icon
 * springs up inside a ring that sweeps round, with what layout it opens in.
 */
@Composable
internal fun LaunchOverlay(visible: Boolean, name: String, layout: String, icon: @Composable () -> Unit) {
    AnimatedVisibility(visible, enter = fadeIn(tween(200)) + scaleIn(spring(Spring.DampingRatioMediumBouncy, Spring.StiffnessLow), initialScale = .85f),
        exit = fadeOut(tween(250)) + scaleOut(tween(250), targetScale = 1.08f)) {
        val primary = MaterialTheme.colorScheme.primary
        val sweep = rememberInfiniteTransition(label = "sweep")
        val angle by sweep.animateFloat(0f, 360f, infiniteRepeatable(tween(1100, easing = LinearEasing)), label = "angle")
        val breathe by sweep.animateFloat(.94f, 1.04f, infiniteRepeatable(tween(900, easing = FastOutSlowInEasing), RepeatMode.Reverse), label = "breathe")
        Column(
            Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background.copy(alpha = .92f)).padding(32.dp),
            verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                Modifier.size(132.dp).drawBehind {
                    val stroke = 5.dp.toPx()
                    drawCircle(primary.copy(alpha = .15f), style = Stroke(stroke))
                    drawArc(primary, angle, 90f, false, topLeft = Offset(stroke / 2, stroke / 2),
                        size = androidx.compose.ui.geometry.Size(this.size.width - stroke, this.size.height - stroke), style = Stroke(stroke, cap = androidx.compose.ui.graphics.StrokeCap.Round))
                },
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    Modifier.size(84.dp).scale(breathe).clip(RoundedCornerShape(24.dp)).background(MaterialTheme.colorScheme.surfaceVariant),
                    contentAlignment = Alignment.Center,
                ) { icon() }
            }
            Spacer(Modifier.height(24.dp))
            Text(name, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center)
            Spacer(Modifier.height(6.dp))
            Text(when (layout) {
                "compact" -> "Opening in compact layout"
                "desktop" -> "Opening in desktop layout"
                else -> "Opening in phone layout"
            }, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(20.dp))
            LinearProgressIndicator(Modifier.size(120.dp, 4.dp).clip(CircleShape))
        }
    }
}
