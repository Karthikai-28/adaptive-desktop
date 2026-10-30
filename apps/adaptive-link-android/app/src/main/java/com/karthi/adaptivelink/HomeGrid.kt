package com.karthi.adaptivelink

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import org.json.JSONObject

/** The sizes of the phone's Home, worked out from the screen. Pure: HomeMetricsTest checks them. */
internal object HomeMetrics {
    const val GUTTER = 12
    const val MIN_CELL = 72
    const val TILE = 56
    const val DOCK_TILE = 52
    const val DOCK_MARGIN = 8
    const val DOCK_PADDING = 10
    const val DOCK_GAP = 8

    /** How far labels follow the system's text size: past it no word fits a cell. */
    const val LABEL_SCALE = 1.15f

    /** Four across on a small phone, five on a large one, fewer for large text, no sprawl on a tablet. */
    fun columns(widthDp: Int, fontScale: Float = 1f): Int =
        ((widthDp - 2 * GUTTER) / (MIN_CELL * fontScale.coerceIn(1f, LABEL_SCALE)).toInt()).coerceIn(3, 8)

    /** The dock's tile: full size while the apps fit, smaller together when they would not. */
    fun dockTile(widthDp: Int, count: Int): Int {
        if (count < 1) return DOCK_TILE
        val room = widthDp - 2 * DOCK_MARGIN - 2 * DOCK_PADDING - (count - 1) * DOCK_GAP
        return (room / count).coerceAtMost(DOCK_TILE)
    }

    /** left, top, right, bottom (exclusive) of what can be seen in an ARGB picture; null if nothing can. */
    fun visibleBounds(pixels: IntArray, width: Int, height: Int, minAlpha: Int = 32): IntArray? {
        var left = width; var top = height; var right = -1; var bottom = -1
        for (y in 0 until height) for (x in 0 until width) {
            if (pixels[y * width + x] ushr 24 < minAlpha) continue
            if (x < left) left = x
            if (x > right) right = x
            if (y < top) top = y
            if (y > bottom) bottom = y
        }
        return if (right < 0) null else intArrayOf(left, top, right + 1, bottom + 1)
    }
}

/** One app's icon on its tile. Every place that shows a tile draws it here, so they all match. */
@Composable
internal fun AppTile(client: LinkClient, app: JSONObject, symbol: ImageVector?, size: Dp) {
    Box(
        Modifier.size(size).clip(RoundedCornerShape(size * .24f)).background(MaterialTheme.colorScheme.surfaceVariant),
        contentAlignment = Alignment.Center,
    ) {
        if (symbol != null) Icon(symbol, null, Modifier.size(size * .58f), tint = MaterialTheme.colorScheme.primary)
        else AppIcon(client, app, size * .8f)
    }
}

/** A launcher cell: the tile with its status on the corner, and a two-line label so that rows stay level. */
@Composable
internal fun AppCell(name: String, status: String, statusColour: Color, modifier: Modifier = Modifier,
                     onLongClick: () -> Unit, onClick: () -> Unit, tile: @Composable () -> Unit) {
    val density = LocalDensity.current
    Column(
        modifier.clip(RoundedCornerShape(16.dp)).pressable(onLongClick = onLongClick, onClick = onClick)
            .semantics { if (status.isNotEmpty()) stateDescription = status }.padding(top = 8.dp, bottom = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box {
            tile()
            if (status.isNotEmpty()) Box(
                Modifier.align(Alignment.TopEnd).padding(top = 1.dp, end = 1.dp).size(12.dp)
                    .border(2.dp, MaterialTheme.colorScheme.background, CircleShape).padding(2.dp).clip(CircleShape).background(statusColour),
            )
        }
        Spacer(Modifier.height(6.dp))
        CompositionLocalProvider(LocalDensity provides Density(density.density, density.fontScale.coerceAtMost(HomeMetrics.LABEL_SCALE))) {
            Text(name, Modifier.fillMaxWidth().padding(horizontal = 2.dp), minLines = 2, maxLines = 2, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.labelSmall, textAlign = TextAlign.Center)
        }
    }
}

/** The pinned apps as plain rows: they live in Home's own scroll, so nothing guesses their height. */
@Composable
internal fun <T> PinnedRows(entries: List<T>, columns: Int, cell: @Composable (T, Modifier) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(horizontal = HomeMetrics.GUTTER.dp)) {
        entries.chunked(columns).forEach { row ->
            Row(Modifier.fillMaxWidth()) {
                row.forEach { cell(it, Modifier.weight(1f)) }
                repeat(columns - row.size) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}

/** One dock entry for [HomeDock]. */
internal class DockEntry(val id: String, val name: String, val running: Boolean)

/** The dock stays above the navigation bar, whatever Home scrolls behind it. */
@Composable
internal fun HomeDock(entries: List<DockEntry>, onOpen: (String) -> Unit, onOrganize: (String) -> Unit, tile: @Composable (String, Dp) -> Unit) {
    if (entries.isEmpty()) return
    BoxWithConstraints(Modifier.fillMaxWidth().padding(vertical = 4.dp), contentAlignment = Alignment.Center) {
        val size = HomeMetrics.dockTile(maxWidth.value.toInt(), entries.size).dp
        Surface(
            shape = RoundedCornerShape(26.dp),
            color = Color(0x77202024),
            border = BorderStroke(0.5.dp, Color(0x33FFFFFF)),
            tonalElevation = 8.dp,
        ) {
            Row(
                Modifier.padding(horizontal = HomeMetrics.DOCK_PADDING.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(HomeMetrics.DOCK_GAP.dp),
            ) {
                entries.forEach { entry ->
                    Column(
                        Modifier.width(size).clip(RoundedCornerShape(size * .24f))
                            .pressable(onLongClick = { onOrganize(entry.id) }) { onOpen(entry.id) }
                            .semantics { contentDescription = entry.name },
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        tile(entry.id, size)
                        Spacer(Modifier.height(3.dp))
                        Box(Modifier.size(4.dp).clip(CircleShape).background(if (entry.running) Color(0xFF30D158) else Color.Transparent))
                    }
                }
            }
        }
    }
}
