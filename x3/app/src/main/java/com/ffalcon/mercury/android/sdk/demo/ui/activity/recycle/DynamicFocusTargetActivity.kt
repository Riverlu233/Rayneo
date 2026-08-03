package com.ffalcon.mercury.android.sdk.demo.ui.activity.recycle

import android.annotation.SuppressLint
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.ffalcon.mercury.android.sdk.core.make3DEffectForSide
import com.ffalcon.mercury.android.sdk.demo.R
import com.ffalcon.mercury.android.sdk.demo.databinding.ActivityDynamicFocusBinding
import com.ffalcon.mercury.android.sdk.touch.TempleAction
import com.ffalcon.mercury.android.sdk.ui.activity.BaseMirrorActivity
import com.ffalcon.mercury.android.sdk.ui.toast.FToast
import com.ffalcon.mercury.android.sdk.ui.util.FixPosFocusTracker
import com.ffalcon.mercury.android.sdk.ui.util.FocusHolder
import com.ffalcon.mercury.android.sdk.ui.util.FocusInfo
import com.ffalcon.mercury.android.sdk.ui.util.FocusViewHandle
import com.ffalcon.mercury.android.sdk.ui.util.addFocusView
import kotlinx.coroutines.launch

class DynamicFocusTargetActivity : BaseMirrorActivity<ActivityDynamicFocusBinding>() {
    private var fixPosFocusTracker: FixPosFocusTracker? = null
    private val focusHolder = FocusHolder(true)
    private val focusHandles = mutableListOf<FocusViewHandle<View>>()

    private lateinit var currentDynamicFocus: FocusViewHandle<View>

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        initFocusTarget()
        initEvent()
    }

    private fun initFocusTarget() {
        // btnAdd is already defined in layout file, use directly
        mBindingPair.setLeft {
            focusHolder.addFocusTarget(
                FocusInfo(
                    btnAdd,
                    eventHandler = { action ->
                        when (action) {
                            is TempleAction.Click -> {
                                addDynamicFocus()
                            }

                            else -> Unit
                        }
                    },
                    focusChangeHandler = { hasFocus ->
                        mBindingPair.updateView {
                            triggerFocus(hasFocus, btnAdd, mBindingPair.checkIsLeft(this))
                        }
                    }
                ),
                FocusInfo(
                    btnRemove,
                    eventHandler = { action ->
                        when (action) {
                            is TempleAction.Click -> {
                                if (focusHandles.contains(currentDynamicFocus)) {
                                    FToast.show("remove dynamic focus target ")
                                    currentDynamicFocus.clearFocusView()
                                    focusHandles.remove(currentDynamicFocus)
                                    if (focusHandles.isNotEmpty()) {
                                        currentDynamicFocus = focusHandles.last()
                                    }
                                }
                            }

                            else -> Unit
                        }
                    },
                    focusChangeHandler = { hasFocus ->
                        mBindingPair.updateView {
                            triggerFocus(hasFocus, btnRemove, mBindingPair.checkIsLeft(this))
                        }
                    }
                )
            )
            focusHolder.currentFocus(btnAdd)
        }

        fixPosFocusTracker = FixPosFocusTracker(focusHolder).apply {
            focusObj.hasFocus = true
        }
    }

    @SuppressLint("SetTextI18n")
    private fun addDynamicFocus() {
        // Extension function API to dynamically add focus View
        // Use mutable reference because handle needs to be used in eventHandler
        var handle: FocusViewHandle<View>? = null
        val size = focusHandles.size
        handle = mBindingPair.addFocusView(
            parent = mBindingPair.left.llParent,
            viewFactory = {
                //todo This is just a demo of dynamically adding different views
                when (size) {
                    1 -> TextView(this@DynamicFocusTargetActivity).apply {
                        text = "dynamic focus target TextView"
                    }

                    2 -> ImageView(this@DynamicFocusTargetActivity).apply {
                        setBackgroundResource(R.mipmap.ic_launcher)
                    }

                    else -> Button(this@DynamicFocusTargetActivity).apply {
                        text = "dynamic focus target"
                        background = null
                    }
                }
            },
            focusHolder = focusHolder,
            focusConfig = {
                // Set layout parameters (LinearLayout)
                layoutParamsFactory = { parent, view ->
                    LinearLayout.LayoutParams(
                        150.dp,
                        ViewGroup.LayoutParams.WRAP_CONTENT
                    ).apply {
                        setMargins(
                            20.dp,
                            5.dp,
                            20.dp,
                            5.dp
                        )
                    }
                }

                eventHandler = { action ->
                    when (action) {
                        is TempleAction.Click -> {
                            FToast.show("dynamic focus target click!!")
                        }

                        else -> Unit
                    }
                }

                onFocusChange = { view, hasFocus, isLeft ->
                    triggerFocus(hasFocus, view, isLeft)
                }
            }
        )

        // Add to list
        focusHandles.add(handle)

        currentDynamicFocus = handle
    }

    private fun initEvent() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.RESUMED) {
                templeActionViewModel.state.collect {
                    when (it) {
                        is TempleAction.DoubleClick -> {
                            finish()
                        }

                        else -> fixPosFocusTracker?.handleFocusTargetEvent(it)
                    }
                }
            }
        }
    }

    private fun triggerFocus(hasFocus: Boolean, view: View?, isLeft: Boolean) {

        view?.let {
            if (view !is ImageView)
                view.setBackgroundColor(
                    getColor(if (hasFocus) com.ffalcon.mercury.android.sdk.R.color.color_rayneo_theme_0 else R.color.black)
                )
            // 3D effect
            make3DEffectForSide(view, isLeft, hasFocus)
        }
    }

    // dp extension function
    private val Int.dp: Int
        get() = (this * this@DynamicFocusTargetActivity.resources.displayMetrics.density).toInt()
}