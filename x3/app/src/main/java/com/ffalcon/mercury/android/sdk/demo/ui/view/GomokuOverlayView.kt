package com.ffalcon.mercury.android.sdk.demo.ui.view

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.util.AttributeSet
import android.view.View
import kotlin.math.min

class GomokuOverlayView @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null
) : View(context, attrs) {

    private val gridPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE // 纯白网格，在空中更清晰
        strokeWidth = 2f
    }

    private val blackPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.BLACK
    }

    // 💡 关键救命稻草：黑棋的白色描边
    private val blackStrokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        style = Paint.Style.STROKE
        strokeWidth = 3f
    }

    private val whitePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
    }

    private val suggestPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.RED
        style = Paint.Style.STROKE
        strokeWidth = 6f
    }

    private var board: List<List<Int>> = emptyList()
    private var suggest: Pair<Int, Int>? = null

    fun update(boardState: List<List<Int>>, next: Pair<Int, Int>?) {
        board = boardState
        suggest = next
        postInvalidateOnAnimation()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (board.isEmpty()) return

        val n = board.size
        val size = min(width, height).toFloat()
        // A board with n intersections has n - 1 gaps.
        val spacing = size / (n - 1).toFloat()
        val cell = spacing
        val offsetX = (width - size) / 2f
        val offsetY = (height - size) / 2f

        // 1. 画网格 (直接画在透明背景上)
        for (i in 0 until n) {
            val y = offsetY + i * spacing
            canvas.drawLine(offsetX, y, offsetX + size, y, gridPaint)
            val x = offsetX + i * spacing
            canvas.drawLine(x, offsetY, x, offsetY + size, gridPaint)
        }

        // 2. 画棋子
        for (r in 0 until n) {
            for (c in 0 until n) {
                val cx = offsetX + c * spacing
                val cy = offsetY + r * spacing
                val radius = spacing * 0.35f

                when (board[r][c]) {
                    1 -> {
                        // 黑子：虽然黑色是透明的，但外围的白圈会勾勒出它的轮廓，非常像 AR 标定框！
                        canvas.drawCircle(cx, cy, radius, blackPaint)
                        canvas.drawCircle(cx, cy, radius, blackStrokePaint)
                    }
                    2 -> {
                        // 白子：直接画白色实心圆
                        canvas.drawCircle(cx, cy, radius, whitePaint)
                    }
                }
            }
        }

        // 3. 画 AI 推荐落子点
        suggest?.let { (r, c) ->
            canvas.drawCircle(
                offsetX + c * spacing,
                offsetY + r * spacing,
                cell * 0.45f, // 红圈比棋子稍微大一圈
                suggestPaint
            )
        }
    }
}
