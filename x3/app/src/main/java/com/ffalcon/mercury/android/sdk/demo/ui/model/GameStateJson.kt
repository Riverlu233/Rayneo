package com.ffalcon.mercury.android.sdk.demo.ui.model

data class GameStateJson(
    val status: String,
    val ai_move: AiMove,
    val board_matrix: List<List<Int>>
    ) {
        data class AiMove(val row: Int, val col: Int)
}