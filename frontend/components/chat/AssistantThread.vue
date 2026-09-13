<template>
  <div ref="host" class="agent-assistant-thread" data-chat-library="ai-elements-vue">
    <Conversation v-if="mounted" ref="conversation" class="agent-thread-root" :initial="false" resize="instant" aria-label="AI 对话" @scroll.capture="emit('scroll', $event)">
      <ConversationContent class="agent-message-list">
        <slot v-if="!messages.length" name="welcome" />
        <Message v-for="message in messages" :key="message.id" :from="message.role" class="agent-message">
          <slot name="message" :message="message" />
        </Message>
      </ConversationContent>
    </Conversation>
  </div>
</template>
<script setup>
import { ref, onMounted, nextTick } from 'vue'
import Conversation from '../ai-elements/conversation/Conversation.vue'
import ConversationContent from '../ai-elements/conversation/ConversationContent.vue'
import Message from '../ai-elements/message/Message.vue'
defineProps({ messages: { type: Array, default: () => [] }, running: Boolean })
const emit = defineEmits(['scroll', 'ready'])
const host = ref(null), mounted = ref(false)
const conversation = ref(null)
// 后端消息 ID 决定节点生命周期；只由 Conversation 管理自动跟随滚动。
onMounted(async () => {
  mounted.value = true
  await nextTick()
  const viewport = conversation.value?.getViewport()
  if (viewport) { viewport.classList.add('agent-conversation'); emit('ready', viewport) }
})
</script>
