package com.ffalcon.mercury.android.sdk.demo.ui.fragment

import android.os.Bundle
import android.view.View
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.get
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.ffalcon.mercury.android.sdk.core.BaseScreenHolder
import com.ffalcon.mercury.android.sdk.core.ViewPair
import com.ffalcon.mercury.android.sdk.demo.databinding.FragmentRecycleviewBinding
import com.ffalcon.mercury.android.sdk.demo.ui.adapter.MovedFocusPosAdapter
import com.ffalcon.mercury.android.sdk.demo.ui.entity.contactList
import com.ffalcon.mercury.android.sdk.ui.toast.FToast
import com.ffalcon.mercury.android.sdk.focus.IFocusable
import com.ffalcon.mercury.android.sdk.focus.releaseFocus
import com.ffalcon.mercury.android.sdk.touch.TempleAction
import com.ffalcon.mercury.android.sdk.touch.TempleActionViewModel
import com.ffalcon.mercury.android.sdk.ui.fragment.BaseMirrorFragment
import com.ffalcon.mercury.android.sdk.ui.util.RecyclerViewFocusTracker
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.isActive

class FragmentRecyclerViewDemo :
    BaseMirrorFragment<FragmentRecycleviewBinding, BaseScreenHolder<FragmentRecycleviewBinding>>(),
    IFocusable {
    override var hasFocus: Boolean = false
        set(value) {
            field = value
            favoriteTracker.focusObj.hasFocus = value
        }


    override var focusParent: IFocusable? = null

    private lateinit var favoriteTracker: RecyclerViewFocusTracker

    override fun onCreateView(rootView: View, savedInstanceState: Bundle?) {
        favoriteTracker = RecyclerViewFocusTracker(
            ViewPair(mBindingPair.left.recyclerView, mBindingPair.right.recyclerView),
            ignoreDelta = 70
        )

        initView()
        initEvent()
    }

    private fun initEvent() {
        // Listen to original events to implement tracking effect

        lifecycleScope.launchWhenResumed {
            val templeActionViewModel =
                ViewModelProvider(requireActivity()).get<TempleActionViewModel>()
            templeActionViewModel.state.collectLatest {
                if (!favoriteTracker.focusObj.hasFocus || !this.isActive || it.consumed) {
                    return@collectLatest
                }
                favoriteTracker.handleActionEvent(it) { action ->
                    when (action) {
                        is TempleAction.DoubleClick -> {
                            action.consumed = true
                            releaseFocus()
                        }

                        is TempleAction.Click -> {
                            if (!action.consumed) {
                                (mBindingPair.left.recyclerView.adapter as MovedFocusPosAdapter)
                                    .getCurrentData()?.apply {
                                        FToast.show(displayName)
                                    }
                            }
                        }

                        else -> {}
                    }
                }
            }
        }
    }

    private fun initView() {
        val mPair = mBindingPair
        mPair.updateView {
            val isLeft = mPair.checkIsLeft(this)
            recyclerView.apply {
                layoutManager = LinearLayoutManager(context)
                adapter = MovedFocusPosAdapter(context, isLeft, favoriteTracker).apply {
                    setData(contactList())
                }
                itemAnimator = null
            }
            favoriteTracker.setCurrentSelectPos(0)
        }
    }


    companion object {
        fun newInstance(content: String): FragmentRecyclerViewDemo {
            val fragment = FragmentRecyclerViewDemo()
            fragment.arguments = Bundle().apply {
                putString("content", content)
            }
            return fragment
        }
    }
}
