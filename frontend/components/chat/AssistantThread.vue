<template>
  <div ref="host" class="agent-assistant-thread" data-chat-library="assistant-ui-vue">
    <AuiProvider v-if="mounted" :config="adapter.config">
      <ThreadPrimitiveRoot class="agent-thread-root">
        <ThreadPrimitiveViewport class="agent-conversation" :scroll-to-bottom-on-run-start="false" @scroll="emit('scroll', $event)">
          <slot v-if="!messages.length" name="welcome" />
          <ThreadPrimitiveMessages>
            <MessageSlot :messages="messageMap"><template #default="scope"><slot name="message" v-bind="scope" /></template></MessageSlot>
          </ThreadPrimitiveMessages>
        </ThreadPrimitiveViewport>
      </ThreadPrimitiveRoot>
    </AuiProvider>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, onBeforeUnmount, shallowRef, watch, nextTick } from 'vue'
import { AuiProvider, ThreadPrimitiveRoot, ThreadPrimitiveViewport, ThreadPrimitiveMessages, MessagePrimitiveRoot, useAuiState } from '@assistant-ui/vue'
import { createAssistantThread } from '~/utils/assistantThread'

const props = defineProps({ messages: { type: Array, default: () => [] }, running: Boolean })
const emit = defineEmits(['scroll', 'ready'])
const host = shallowRef(null), mounted = shallowRef(false)
const adapter = shallowRef(null)
const messageMap = computed(() => new Map(props.messages.map(message => [message.id, message])))
// 保留领域消息原有的 Vue 插槽；以 ID 绑定生命周期，流式更新不重建工具详情。
const MessageSlot = defineComponent({
  props: { messages: { type: Map, required: true } },
  setup(slotProps, { slots }) {
    const id = useAuiState(state => state.message.id)
    return () => {
      const message = slotProps.messages.get(id.value)
      return message ? h(MessagePrimitiveRoot, { class: 'agent-message' }, { default: () => slots.default?.({ message }) }) : null
    }
  },
})
const ready = async () => { await nextTick(); if (mounted.value) emit('ready', host.value?.querySelector('.agent-conversation')) }
onMounted(() => {
  // 只在客户端创建会话运行时，避免服务端渲染共享或挂载状态。
  adapter.value = createAssistantThread({ messages: props.messages, running: props.running })
  mounted.value = true
  ready()
})
watch(() => [props.messages, props.running], () => { adapter.value?.update({ messages: props.messages, running: props.running }); ready() }, { deep: true })
onBeforeUnmount(() => { mounted.value = false })
</script>
