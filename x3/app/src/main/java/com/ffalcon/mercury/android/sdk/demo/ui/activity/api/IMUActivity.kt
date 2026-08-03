package com.ffalcon.mercury.android.sdk.demo.ui.activity.api

import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.ffalcon.mercury.android.sdk.demo.databinding.ActivityImuBinding
import com.ffalcon.mercury.android.sdk.touch.TempleAction
import com.ffalcon.mercury.android.sdk.ui.activity.BaseMirrorActivity
import kotlinx.coroutines.launch


class IMUActivity : BaseMirrorActivity<ActivityImuBinding>(), SensorEventListener {
    // Sensor manager and sensor objects
    private lateinit var sensorManager: SensorManager
    private var accelerometerSensor: Sensor? = null
    private var gyroscopeSensor: Sensor? = null
    private var magnetometerSensor: Sensor? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        initIMU()
        initEvent()
    }

    private fun initIMU() {
        // 1. Get SensorManager system service
        sensorManager = getSystemService(SENSOR_SERVICE) as SensorManager

        // 2. Get default sensor instances
        // Use TYPE_ACCELEROMETER to get accelerometer
        accelerometerSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        // Use TYPE_GYROSCOPE to get gyroscope
        gyroscopeSensor = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
        // Use TYPE_MAGNETIC_FIELD to get magnetometer
        magnetometerSensor = sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)

        mBindingPair.updateView {
            // Check if device supports these sensors
            if (accelerometerSensor == null) {
                tvAccelerometer.text = "Accelerometer unavailable"
            }
            if (gyroscopeSensor == null) {
                tvGyroscope.text = "Gyroscope unavailable"
            }
            if (magnetometerSensor == null) {
                tvMagnetometer.text = "Magnetometer unavailable"
            }
        }
    }

    override fun onResume() {
        super.onResume()
        // 3. Register sensor listeners
        // Parameters: listener, sensor object, sampling delay (microseconds)
        accelerometerSensor?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_NORMAL)
        }
        gyroscopeSensor?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_NORMAL)
        }
        magnetometerSensor?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_NORMAL)
        }
    }


    override fun onPause() {
        super.onPause()
        // 4. Very important! Unregister listeners when paused to save battery
        sensorManager.unregisterListener(this)
    }

    private fun initEvent() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.RESUMED) {
                templeActionViewModel.state.collect {
                    when (it) {
                        is TempleAction.DoubleClick -> {
                            finish()
                        }

                        else -> Unit
                    }
                }
            }
        }
    }

    // Callback when sensor data changes
    override fun onSensorChanged(event: SensorEvent) {
        mBindingPair.updateView {
            // event.values is a float array containing X, Y, Z axis data
            when (event.sensor.type) {
                Sensor.TYPE_ACCELEROMETER -> {
                    val x = event.values[0]
                    val y = event.values[1]
                    val z = event.values[2]
                    tvAccelerometer.text =
                        "Accelerometer:\nX: %.2f m/s²\nY: %.2f m/s²\nZ: %.2f m/s²".format(x, y, z)
                }

                Sensor.TYPE_GYROSCOPE -> {
                    val x = event.values[0]
                    val y = event.values[1]
                    val z = event.values[2]
                    tvGyroscope.text =
                        "Gyroscope:\nX: %.2f rad/s\nY: %.2f rad/s\nZ: %.2f rad/s".format(x, y, z)
                }

                Sensor.TYPE_MAGNETIC_FIELD -> {
                    val x = event.values[0]
                    val y = event.values[1]
                    val z = event.values[2]
                    tvMagnetometer.text =
                        "Magnetometer:\nX: %.2f μT\nY: %.2f μT\nZ: %.2f μT".format(x, y, z)
                }
            }
        }
    }

    // Callback when sensor accuracy changes (usually no need to handle)
    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
        // Can handle accuracy changes here, e.g., from low accuracy to high accuracy
    }

}