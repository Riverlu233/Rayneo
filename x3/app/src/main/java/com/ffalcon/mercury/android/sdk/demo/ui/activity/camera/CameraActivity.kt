package com.ffalcon.mercury.android.sdk.demo.ui.activity.camera

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.SurfaceTexture
import android.graphics.YuvImage
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.params.OutputConfiguration
import android.hardware.camera2.params.SessionConfiguration
import android.media.Image
import android.media.ImageReader
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import android.util.Range
import android.util.Size
import android.view.Surface
import android.view.TextureView.SurfaceTextureListener
import androidx.annotation.RequiresApi
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.ffalcon.mercury.android.sdk.demo.databinding.ActivityCameraBinding
import com.ffalcon.mercury.android.sdk.touch.TempleAction
import com.ffalcon.mercury.android.sdk.ui.activity.BaseMirrorActivity
import com.ffalcon.mercury.android.sdk.util.FLogger
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.ByteArrayOutputStream
import java.io.BufferedOutputStream
import java.io.DataOutputStream
import java.nio.ByteBuffer
import java.net.Socket
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

class CameraActivity : BaseMirrorActivity<ActivityCameraBinding>() {
    private companion object {
        const val COMPUTER_IP = "192.168.43.248"
        const val TRANSFER_PORT = 9999
    }

    private var isVGA = true
    private var useTcp = false
    private val surfaceList = mutableListOf<Surface>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        isVGA = intent.getBooleanExtra("isVGA", false)
        useTcp = intent.getBooleanExtra("useTcp", false)
        backHandlerThread.start()

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                templeActionViewModel.state.collect {
                    when (it) {
                        is TempleAction.Click -> {
                            takePhoto.set(true)
                        }

                        is TempleAction.DoubleClick -> {
                            finish()
                        }

                        else -> {

                        }
                    }
                }
            }
        }

        mBindingPair.updateView {
            this.cameraPreview.surfaceTextureListener = object : SurfaceTextureListener {
                var mSurface: Surface? = null
                override fun onSurfaceTextureAvailable(
                    surface: SurfaceTexture,
                    width: Int,
                    height: Int,
                ) {
                    Log.d("Camera onSurfaceTextureAvailable", "width=$width,height=$height")
                    // Ignore ConstraintLayout calculated size, use fixed resolution supported by camera
                    if (isVGA) {
                        surface.setDefaultBufferSize(
                            640,
                            480
                        )
                    } else {
                        surface.setDefaultBufferSize(
                            1920,
                            1080
                        )
                    }


                    val surface2 = Surface(cameraPreview.surfaceTexture)
                    surfaceList.add(surface2)
                    mSurface = surface2
                    if (surfaceList.size == 2) {
                        lifecycleScope.launch {
                            delay(100L)
                            setupCamera2()
                        }
                    }
                }

                override fun onSurfaceTextureSizeChanged(
                    surface: SurfaceTexture,
                    width: Int,
                    height: Int,
                ) {
                }

                override fun onSurfaceTextureDestroyed(surface: SurfaceTexture): Boolean {
                    mSurface?.release()
                    return true
                }

                override fun onSurfaceTextureUpdated(surface: SurfaceTexture) {
                }

            }
        }

        //enumerateCameraResolutions()
        printCameraCapabilities()
    }

    override fun onStop() {
        super.onStop()
        Thread {
            closeCamera()
        }.start()
    }

    private var cameraDevice: CameraDevice? = null
    private lateinit var cameraManager: CameraManager
    private val atomicBoolean = AtomicBoolean(false)
    private var cameraCaptureSession: CameraCaptureSession? = null
    private lateinit var backHandler: Handler
    private var imageReader: ImageReader? = null
    private var cameraJob: Job? = null
    var takePhoto = AtomicBoolean(false)

    private val backHandlerThread = object : HandlerThread("background") {
        override fun onLooperPrepared() {
            super.onLooperPrepared()
            backHandler = Handler(this.looper)
        }
    }

    private val transportExecutor = Executors.newSingleThreadExecutor()
    private val tcpLock = Any()
    private val udpSocket = DatagramSocket()
    private var tcpSocket: Socket? = null
    private var tcpOutputStream: DataOutputStream? = null

    private val stateCallback = object : CameraDevice.StateCallback() {
        @RequiresApi(Build.VERSION_CODES.P)
        override fun onOpened(p0: CameraDevice) {
            cameraJob = lifecycleScope.launch {
                cameraDevice = p0
                delay(100L)
                if (cameraDevice == p0) {
                    setUpImageReader(p0)
                }
            }
        }

        override fun onDisconnected(p0: CameraDevice) {
            cameraDevice = null
            cameraJob?.cancel()
        }


        override fun onError(p0: CameraDevice, p1: Int) {
        }

    }

    @SuppressLint("MissingPermission")
    private fun setupCamera2() {
        cameraManager = getSystemService(Context.CAMERA_SERVICE) as CameraManager
        val cameraId =
             if (isVGA) cameraManager.cameraIdList[1] else cameraManager.cameraIdList.first()
        // val cameraId = cameraManager.cameraIdList.first()
        cameraManager.openCamera(cameraId, stateCallback, null)

    }

    var openTime = -1L

    @RequiresApi(Build.VERSION_CODES.P)
    fun setUpImageReader(camera: CameraDevice) {
        imageReader?.close()
        imageReader = if (isVGA)
            ImageReader.newInstance(640, 480, ImageFormat.YUV_420_888, 10)
        else
            ImageReader.newInstance(1920, 1080, ImageFormat.YUV_420_888, 10)


        cameraDevice = camera
        openTime = -1L
        imageReader?.setOnImageAvailableListener({ reader ->


            if (openTime == -1L) {
                openTime = System.currentTimeMillis()
                return@setOnImageAvailableListener
            }
            if ((System.currentTimeMillis() - openTime) < 1000L) {
                return@setOnImageAvailableListener
            }
            val image = reader.acquireLatestImage() ?: run {
                return@setOnImageAvailableListener
            }

            sendImageToComputer(image)

            if (takePhoto.get()) {
                takePhoto.set(false)
                val bitmap = imageToBitmap(image)
                bitmap?.let {
                    runOnUiThread {
                        mBindingPair.updateView {
                            this.thumbnailView.setImageBitmap(it)
                        }
                    }
                } ?: Log.e("CameraActivity", "Image convert to bitmap failed! ")
            }
            image.close()

        }, backHandler)

        val captureRequestBuilder = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW)
            .apply {
                addTarget(imageReader!!.surface)
                for (item in surfaceList) {
                    addTarget(item)
                }
                val fpsRange = Range(5, 10)
                set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, fpsRange)

            }
        val outputConfig = OutputConfiguration(imageReader!!.surface)
        val outputConfig2 = OutputConfiguration(surfaceList[0])
        val outputConfig3 = OutputConfiguration(surfaceList[1])
        val outputs = listOf(outputConfig, outputConfig2, outputConfig3)
        val sessionConfig = SessionConfiguration(
            SessionConfiguration.SESSION_REGULAR,
            outputs,
            Executors.newSingleThreadExecutor(),
            object : CameraCaptureSession.StateCallback() {

                override fun onConfigured(session: CameraCaptureSession) {
                    session.setRepeatingRequest(captureRequestBuilder.build(), null, null)
                    cameraCaptureSession = session
                }

                override fun onConfigureFailed(session: CameraCaptureSession) {
                }
            }
        )
        camera.createCaptureSession(sessionConfig)
    }

    private fun closeCamera() {
        // 1. 第一时间告诉 ImageReader 的回调：不要再处理新图了！
        atomicBoolean.set(false)

        try {
            // 2. 极其重要：打断底层的图像输出循环，防止 close() 时死锁
            if (null != cameraCaptureSession) {
                try {
                    cameraCaptureSession!!.stopRepeating()
                    cameraCaptureSession!!.abortCaptures()
                } catch (e: Exception) {
                    Log.e("Camera", "停止捕获异常", e)
                }
                cameraCaptureSession!!.close()
                cameraCaptureSession = null
            }

            // 3. 安全关闭相机设备
            if (null != cameraDevice) {
                cameraDevice!!.close()
                cameraDevice = null
            }

            // 4. 关闭图像读取器
            if (null != imageReader) {
                imageReader?.close()
                imageReader = null
            }
        } catch (e: Exception) {
            Log.e("Camera", "关闭相机异常", e)
        } finally {
            // 5. 最后清理网络和线程池 (建议这些操作如果耗时，最好也是在子线程中)
            try {
                transportExecutor.shutdownNow()
                udpSocket?.close() // 注意判空
                closeTcpConnection()
            } catch (e: Exception) {
                Log.e("Camera", "关闭网络异常", e)
            }
        }
    }

    private fun imageToBitmap(image: Image): Bitmap? {
        val planes = image.planes
        val buffer: ByteBuffer = planes[0].buffer
        val ySize = buffer.remaining()

        val uBuffer: ByteBuffer = planes[1].buffer
        val uSize = uBuffer.remaining()

        val vBuffer: ByteBuffer = planes[2].buffer
        val vSize = vBuffer.remaining()

        val nv21 = ByteArray(ySize + uSize + vSize)
        buffer.get(nv21, 0, ySize)
        vBuffer.get(nv21, ySize, vSize)
        uBuffer.get(nv21, ySize + vSize, uSize)

        val yuvImage = YuvImage(nv21, ImageFormat.NV21, image.width, image.height, null)
        val out = ByteArrayOutputStream()
        yuvImage.compressToJpeg(Rect(0, 0, yuvImage.width, yuvImage.height), 100, out)
        val imageBytes = out.toByteArray()
        out.close()
        return BitmapFactory.decodeByteArray(imageBytes, 0, imageBytes.size)
    }

    private fun enumerateCameraResolutions() {
        val cameraManager = getSystemService(CAMERA_SERVICE) as CameraManager
        val cameraIdList = cameraManager.cameraIdList

        for (cameraId in cameraIdList) {
            val characteristics = cameraManager.getCameraCharacteristics(cameraId)
            val map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)

            if (map != null) {
                val previewSizes = map.getOutputSizes(SurfaceTexture::class.java)
                val pictureSizes = map.getOutputSizes(ImageFormat.JPEG)

                Log.d("camera", "Camera ID: $cameraId")
                Log.d("camera", "Supported Preview Sizes:")
                for (size in previewSizes) {
                    Log.d("camera", "  ${size.width}x${size.height}")
                }

                Log.d("camera", "Supported Picture Sizes:")
                for (size in pictureSizes) {
                    Log.d("camera", "  ${size.width}x${size.height}")
                }
            }
        }
    }

    /**
     * Print camera supported parameters and parameter ranges
     */
    @SuppressLint("LongLogTag")
    private fun printCameraCapabilities() {
        val cameraManager = getSystemService(CAMERA_SERVICE) as CameraManager
        val cameraIdList = cameraManager.cameraIdList

        Log.d("CameraCapabilities", "=== Detected ${cameraIdList.size} cameras ===")

        for (cameraId in cameraIdList) {
            try {
                val characteristics = cameraManager.getCameraCharacteristics(cameraId)

                Log.d("CameraCapabilities", "\n📷 Camera ID: $cameraId")
                Log.d("CameraCapabilities", "----------------------------------------")

                // 1. Basic camera information
                printBasicInfo(characteristics, cameraId)

                // 2. Resolution information
                printResolutionInfo(characteristics)

                // 3. Exposure related parameters
                printExposureCapabilities(characteristics)

                // 4. Focus related parameters
                printFocusCapabilities(characteristics)

                // 5. White balance related parameters
                printWhiteBalanceCapabilities(characteristics)

                // 6. Other image quality parameters
                printImageQualityCapabilities(characteristics)

                // 7. Flash information
                printFlashCapabilities(characteristics)

                // 8. Frame rate information
                printFrameRateCapabilities(characteristics)

            } catch (e: Exception) {
                Log.e("CameraCapabilities", "Failed to get camera $cameraId information: ${e.message}")
            }
        }
    }

    /**
     * Print basic camera information
     */
    private fun printBasicInfo(characteristics: CameraCharacteristics, cameraId: String) {
        val lensFacing = characteristics.get(CameraCharacteristics.LENS_FACING)
        val lensFacingStr = when (lensFacing) {
            CameraCharacteristics.LENS_FACING_FRONT -> "Front"
            CameraCharacteristics.LENS_FACING_BACK -> "Back"
            CameraCharacteristics.LENS_FACING_EXTERNAL -> "External"
            else -> "Unknown"
        }
        Log.d("CameraCapabilities", "📱 Camera type: $lensFacingStr")

        val sensorOrientation = characteristics.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 0
        Log.d("CameraCapabilities", "🔄 Sensor orientation: $sensorOrientation°")

        val hardwareLevel = characteristics.get(CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL)
        val levelStr = when (hardwareLevel) {
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_LEGACY -> "LEGACY"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_LIMITED -> "LIMITED"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_FULL -> "FULL"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_3 -> "LEVEL_3"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_EXTERNAL -> "EXTERNAL"
            else -> "UNKNOWN"
        }
        Log.d("CameraCapabilities", "⚙️ Hardware support level: $levelStr")
    }

    /**
     * Print resolution information
     */
    private fun printResolutionInfo(characteristics: CameraCharacteristics) {
        val map =
            characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ?: return

        Log.d("CameraCapabilities", "\n📐 Resolution support:")

        // Preview resolution
        val previewSizes = map.getOutputSizes(SurfaceTexture::class.java)
        Log.d("CameraCapabilities", "  Preview resolution (${previewSizes.size} types):")
        previewSizes.sortedByDescending { it.width * it.height }
            .take(10) // Only show first 10
            .forEach { size ->
                Log.d(
                    "CameraCapabilities",
                    "    ${size.width} x ${size.height} (${
                        String.format(
                            "%.1f",
                            size.width * size.height / 1000000.0
                        )
                    }MP)"
                )
            }

        // Photo resolution
        val photoSizes = map.getOutputSizes(ImageFormat.JPEG)
        Log.d("CameraCapabilities", "  Photo resolution (${photoSizes.size} types):")
        photoSizes.sortedByDescending { it.width * it.height }
            .take(10)
            .forEach { size ->
                Log.d(
                    "CameraCapabilities",
                    "    ${size.width} x ${size.height} (${
                        String.format(
                            "%.1f",
                            size.width * size.height / 1000000.0
                        )
                    }MP)"
                )
            }
    }

    /**
     * Print exposure related capabilities
     */
    private fun printExposureCapabilities(characteristics: CameraCharacteristics) {
        Log.d("CameraCapabilities", "\n☀️ Exposure parameters:")

        // ISO range
        val isoRange = characteristics.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE)
        Log.d("CameraCapabilities", "  ISO range: ${isoRange?.lower} - ${isoRange?.upper}")

        // Exposure time range (nanoseconds)
        val exposureTimeRange =
            characteristics.get(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE)
        exposureTimeRange?.let {
            val minMs = String.format("%.3f", it.lower / 1000000.0)
            val maxMs = String.format("%.3f", it.upper / 1000000.0)
            Log.d("CameraCapabilities", "  Exposure time: $minMs ms - $maxMs ms")
        }

        // Exposure compensation range
        val exposureCompensationRange =
            characteristics.get(CameraCharacteristics.CONTROL_AE_COMPENSATION_RANGE)
        val exposureCompensationStep =
            characteristics.get(CameraCharacteristics.CONTROL_AE_COMPENSATION_STEP)
        Log.d(
            "CameraCapabilities",
            "  Exposure compensation: ${exposureCompensationRange?.lower} - ${exposureCompensationRange?.upper} (step: $exposureCompensationStep)"
        )

        // Supported AE modes
        val aeModes = characteristics.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_MODES)
        Log.d("CameraCapabilities", "  AE modes: ${aeModes?.contentToString()}")
    }

    /**
     * Print focus related capabilities
     */
    private fun printFocusCapabilities(characteristics: CameraCharacteristics) {
        Log.d("CameraCapabilities", "\n🎯 Focus parameters:")

        // Supported focus modes
        val afModes = characteristics.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES)
        Log.d("CameraCapabilities", "  Focus modes: ${afModes?.contentToString()}")

        // Minimum focus distance
        val minFocusDistance =
            characteristics.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE)
        Log.d("CameraCapabilities", "  Minimum focus distance: $minFocusDistance")

        // Focus distance range
        val focusDistanceRange =
            characteristics.get(CameraCharacteristics.LENS_INFO_FOCUS_DISTANCE_CALIBRATION)
        val calibrationStr = when (focusDistanceRange) {
            CameraCharacteristics.LENS_INFO_FOCUS_DISTANCE_CALIBRATION_APPROXIMATE -> "APPROXIMATE"
            CameraCharacteristics.LENS_INFO_FOCUS_DISTANCE_CALIBRATION_CALIBRATED -> "CALIBRATED"
            CameraCharacteristics.LENS_INFO_FOCUS_DISTANCE_CALIBRATION_UNCALIBRATED -> "UNCALIBRATED"
            else -> "UNKNOWN"
        }
        Log.d("CameraCapabilities", "  Focus distance calibration: $calibrationStr")
    }

    /**
     * Print white balance related capabilities
     */
    private fun printWhiteBalanceCapabilities(characteristics: CameraCharacteristics) {
        Log.d("CameraCapabilities", "\n🎨 White balance parameters:")

        // Supported AWB modes
        val awbModes = characteristics.get(CameraCharacteristics.CONTROL_AWB_AVAILABLE_MODES)
        Log.d("CameraCapabilities", "  White balance modes: ${awbModes?.contentToString()}")
    }

    /**
     * Print image quality parameters
     */
    private fun printImageQualityCapabilities(characteristics: CameraCharacteristics) {
        Log.d("CameraCapabilities", "\n🖼️ Image quality parameters:")

        // Supported scene modes
        val sceneModes = characteristics.get(CameraCharacteristics.CONTROL_AVAILABLE_SCENE_MODES)
        Log.d("CameraCapabilities", "  Scene modes: ${sceneModes?.contentToString()}")

        // Supported effect modes
        val effectModes = characteristics.get(CameraCharacteristics.CONTROL_AVAILABLE_EFFECTS)
        Log.d("CameraCapabilities", "  Effect modes: ${effectModes?.contentToString()}")

        // Whether RAW is supported
        val rawSizes = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            ?.getOutputSizes(ImageFormat.RAW_SENSOR)
        Log.d(
            "CameraCapabilities",
            "  RAW format support: ${if (rawSizes != null && rawSizes.isNotEmpty()) "Yes" else "No"}"
        )
    }

    /**
     * Print flash information
     */
    private fun printFlashCapabilities(characteristics: CameraCharacteristics) {
        Log.d("CameraCapabilities", "\n💡 Flash information:")

        val flashAvailable =
            characteristics.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) ?: false
        Log.d("CameraCapabilities", "  Flash available: $flashAvailable")
    }

    /**
     * Print frame rate information
     */
    private fun printFrameRateCapabilities(characteristics: CameraCharacteristics) {
        Log.d("CameraCapabilities", "\n Frame rate information:")

        val fpsRanges =
            characteristics.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)
        Log.d("CameraCapabilities", "  Supported frame rate ranges:")
        fpsRanges?.forEach { range ->
            Log.d("CameraCapabilities", "    ${range.lower} - ${range.upper} fps")
        }
    }

    /** Encodes one camera frame as JPEG and dispatches it through the selected transport. */
    private fun sendImageToComputer(image: Image) {
        val width = image.width
        val height = image.height

        // 1. 安全地将 YUV_420_888 转换为 NV21 字节数组
        val nv21 = yuv420888ToNv21(image)

        // 2. 将 NV21 压缩为 JPEG
        val yuvImage = YuvImage(nv21, ImageFormat.NV21, width, height, null)
        val out = ByteArrayOutputStream()
        // 压缩质量设为 50，降低网络传输压力
        yuvImage.compressToJpeg(Rect(0, 0, width, height), 50, out)
        val jpegBytes = out.toByteArray()
        out.close()

        transportExecutor.execute {
            if (useTcp) {
                sendTcpFrame(jpegBytes)
            } else {
                sendUdpFrame(jpegBytes)
            }
        }
    }

    /** Sends one JPEG frame as a UDP datagram. */
    private fun sendUdpFrame(jpegBytes: ByteArray) {
        try {
            val address = InetAddress.getByName(COMPUTER_IP)
            val packet = DatagramPacket(
                jpegBytes,
                jpegBytes.size,
                address,
                TRANSFER_PORT,
            )
            udpSocket.send(packet)
        } catch (exception: Exception) {
            Log.e("CameraActivity", "UDP frame send failed", exception)
        }
    }

    /** Sends one JPEG frame over TCP with a four-byte big-endian length prefix. */
    private fun sendTcpFrame(jpegBytes: ByteArray) {
        synchronized(tcpLock) {
            try {
                if (tcpSocket == null || tcpSocket!!.isClosed) {
                    val socket = Socket(COMPUTER_IP, TRANSFER_PORT)
                    socket.tcpNoDelay = true
                    tcpSocket = socket
                    tcpOutputStream = DataOutputStream(
                        BufferedOutputStream(socket.getOutputStream())
                    )
                }

                val outputStream = tcpOutputStream ?: return
                outputStream.writeInt(jpegBytes.size)
                outputStream.write(jpegBytes)
                outputStream.flush()
            } catch (exception: Exception) {
                Log.e("CameraActivity", "TCP frame send failed", exception)
                closeTcpConnectionLocked()
            }
        }
    }

    /** Closes the TCP connection and clears its sender state. */
    private fun closeTcpConnection() {
        synchronized(tcpLock) {
            closeTcpConnectionLocked()
        }
    }

    /** Closes the TCP connection while the TCP lock is held. */
    private fun closeTcpConnectionLocked() {
        try {
            tcpOutputStream?.close()
        } catch (_: Exception) {
        }
        try {
            tcpSocket?.close()
        } catch (_: Exception) {
        }
        tcpOutputStream = null
        tcpSocket = null
    }

    /**
     * 严格按照 Android Image 规范提取 YUV_420_888 转成 NV21
     */
    private fun yuv420888ToNv21(image: Image): ByteArray {
        val width = image.width
        val height = image.height
        val ySize = width * height
        val uvSize = width * height / 2
        val nv21 = ByteArray(ySize + uvSize)

        val planes = image.planes
        val yBuffer = planes[0].buffer
        val uBuffer = planes[1].buffer
        val vBuffer = planes[2].buffer

        val yRowStride = planes[0].rowStride
        val uRowStride = planes[1].rowStride
        val vRowStride = planes[2].rowStride
        val uPixelStride = planes[1].pixelStride
        val vPixelStride = planes[2].pixelStride

        // 1. 复制 Y 分量（处理 rowStride 填充）
        var pos = 0
        if (yRowStride == width) {
            yBuffer.get(nv21, 0, ySize)
            pos += ySize
        } else {
            for (row in 0 until height) {
                yBuffer.position(row * yRowStride)
                yBuffer.get(nv21, pos, width)
                pos += width
            }
        }

        // 2. 按照 NV21 格式（V, U 交替）提取色度分量
        val chromaHeight = height / 2
        val chromaWidth = width / 2

        for (row in 0 until chromaHeight) {
            for (col in 0 until chromaWidth) {
                val vIndex = row * vRowStride + col * vPixelStride
                val uIndex = row * uRowStride + col * uPixelStride

                vBuffer.position(vIndex)
                nv21[pos++] = vBuffer.get()

                uBuffer.position(uIndex)
                nv21[pos++] = uBuffer.get()
            }
        }

        return nv21
    }
}
