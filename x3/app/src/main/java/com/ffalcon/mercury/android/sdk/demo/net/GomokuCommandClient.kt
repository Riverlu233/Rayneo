package com.ffalcon.mercury.android.sdk.demo.net

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.io.DataInputStream
import java.net.InetSocketAddress
import java.net.Socket
import com.google.gson.Gson
import com.ffalcon.mercury.android.sdk.demo.ui.model.GameStateJson

class GomokuCommandClient(
    private val ip: String,
    private val port: Int = 9988,
    private val onGameState: (GameStateJson) -> Unit,
    private val onDisconnected: () -> Unit = {},
    private val timeoutMs: Int = 5000
) {
    private var socket: Socket? = null
    private var input: DataInputStream? = null

    companion object {
        private const val TAG = "GomokuClient"
    }

    fun start(scope: CoroutineScope) {
        scope.launch(Dispatchers.IO) {
            Log.d(TAG, "GomokuCommandClient 启动协程，准备连接 $ip:$port")
            while (isActive) {
                try {
                    socket?.close()
                    socket = Socket()
                    socket!!.connect(InetSocketAddress(ip, port), timeoutMs)
                    socket!!.tcpNoDelay = true
                    input = DataInputStream(socket!!.getInputStream())

                    Log.d(TAG, "成功连接到 PC 指令服务端！")

                    while (isActive && socket?.isConnected == true) {
                        val len = input?.readInt() ?: break
                        Log.d(TAG, "收到数据包长度標头: $len 字节")

                        if (len <= 0 || len > 8 * 1024 * 1024) {
                            Log.e(TAG, "数据长度异常: $len")
                            break
                        }

                        val buf = ByteArray(len)
                        input?.readFully(buf)
                        val text = buf.toString(Charsets.UTF_8)

                        Log.d(TAG, "成功收到原始 JSON 文本: $text")

                        try {
                            val obj = Gson().fromJson(text, GameStateJson::class.java)
                            Log.d(TAG, "JSON 解析成功，准备回调 UI，ai_move: ${obj.ai_move}")
                            onGameState(obj)
                        } catch (jsonEx: Exception) {
                            Log.e(TAG, "JSON 解析崩溃！原文: $text", jsonEx)
                        }
                    }
                } catch (e: Exception) {
                    // 💡 打印出所有被吞掉的网络异常！
                    Log.e(TAG, "网络连接或读取发生异常", e)
                    onDisconnected()
                    kotlinx.coroutines.delay(1000)
                }
            }
        }
    }

    fun close() {
        Log.d(TAG, "关闭 GomokuCommandClient 连接")
        try { input?.close() } catch (_: Exception) {}
        try { socket?.close() } catch (_: Exception) {}
        input = null
        socket = null
    }
}