import { openMessageExternalUrl } from '~/lib/chat/message-links'

// 开发者联系方式只在这里维护一份：跳转 URL、提示文案与各处按钮文案都从它拼
export const DEVELOPER_QQ = '3434549571'

export const FEATURE_UNAVAILABLE_MESSAGE = `当前版本仅展示该功能入口，暂时无法执行。请添加 QQ ${DEVELOPER_QQ}（备注「高级版」）联系开发者获取支持。`

export const openDeveloperContact = () => openMessageExternalUrl(`https://wpa.qq.com/msgrd?v=3&uin=${DEVELOPER_QQ}&site=qq&menu=yes`)
