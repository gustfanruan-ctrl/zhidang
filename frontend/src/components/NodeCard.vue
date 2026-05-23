<template>
  <g :transform="`translate(${x}, ${y})`" class="node-group" @click="$emit('click', node)">
    <rect
      :x="0" :y="0"
      :width="NODE_W"
      :height="cardH"
      :rx="8" ry="8"
      :fill="isOrphan ? '#fffef0' : '#fffde7'"
      :stroke="isOrphan ? '#cbd5e1' : cardBorderColor"
      :stroke-dasharray="isOrphan ? '4 3' : 'none'"
      :stroke-width="1.5"
      filter="url(#card-shadow)"
      class="card-bg"
    />
    <!-- left color bar -->
    <rect :x="0" :y="0" :width="4" :height="cardH" :rx="2" :fill="colorBar" />
    <!-- name -->
    <text :x="12" :y="nameY" class="node-name">{{ node.name }}</text>
    <!-- subtitle -->
    <text :x="12" :y="subY" class="node-sub">{{ subtitle }}</text>
    <!-- type badge -->
    <rect :x="NODE_W - 36" :y="6" :width="28" :height="16" :rx="4" :fill="badgeBg" />
    <text :x="NODE_W - 22" :y="17" class="node-badge-text" text-anchor="middle">{{ typeLabel }}</text>
    <!-- collapse button / badge -->
    <template v-if="node.type === 'department' && childCount > 0">
      <template v-if="collapsed">
        <circle :cx="btnCX" :cy="btnCY" r="10" fill="#3b82f6" />
        <text :x="btnCX" :y="btnCY + 1" class="collapse-count" text-anchor="middle" dominant-baseline="middle">+{{ descendantCount }}</text>
      </template>
      <template v-else>
        <rect :x="btnCX - 8" :y="btnCY - 8" :width="16" :height="16" :rx="4"
          fill="#f1f5f9" stroke="#cbd5e1" class="collapse-btn-rect"
          @click.stop="$emit('toggle', node.id)" />
        <text :x="btnCX" :y="btnCY + 1" class="collapse-btn-text" text-anchor="middle" dominant-baseline="middle"
          @click.stop="$emit('toggle', node.id)">−</text>
      </template>
    </template>
  </g>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  node: { type: Object, required: true },
  x: { type: Number, default: 0 },
  y: { type: Number, default: 0 },
  collapsed: { type: Boolean, default: false },
  childCount: { type: Number, default: 0 },
  descendantCount: { type: Number, default: 0 },
  isOrphan: { type: Boolean, default: false },
})

defineEmits(['click', 'toggle'])

const NODE_W = 168
const cardH = computed(() => props.isOrphan ? 56 : 68)
const nameY = computed(() => props.isOrphan ? 20 : 22)
const subY = computed(() => props.isOrphan ? 36 : 40)

const btnCX = computed(() => NODE_W - 12)
const btnCY = computed(() => props.isOrphan ? 46 : 58)

const colorBar = computed(() => {
  switch (props.node.type) {
    case 'department': return '#3b82f6'
    case 'person': return '#1565c0'
    default: return '#94a3b8'
  }
})

const cardBorderColor = computed(() => {
  if (props.isOrphan) return '#cbd5e1'
  switch (props.node.type) {
    case 'department': return '#3b82f6'
    case 'person': return '#1565c0'
    default: return '#94a3b8'
  }
})

const subtitle = computed(() => {
  if (props.node.type === 'department') {
    const s = props.node.size
    return s != null ? `${s} 名成员` : ''
  }
  return props.node.position || ''
})

const typeLabel = computed(() => {
  switch (props.node.type) {
    case 'department': return '部门'
    case 'person': return '人员'
    default: return props.node.type || ''
  }
})

const badgeBg = computed(() => {
  return props.node.type === 'department' ? '#dbeafe' : '#d1fae5'
})
</script>

<style scoped>
.node-group {
  cursor: pointer;
  transition: opacity 0.15s;
}
.node-group:hover .card-bg {
  stroke: #94a3b8;
}
.node-name {
  font-size: 14px;
  font-weight: 700;
  fill: #c62828;
  font-family: inherit;
}
.node-sub {
  font-size: 12px;
  fill: #546e7a;
  font-family: inherit;
}
.node-badge-text {
  font-size: 10px;
  fill: #475569;
  font-family: inherit;
}
.collapse-btn-rect {
  cursor: pointer;
}
.collapse-btn-text {
  font-size: 12px;
  fill: #64748b;
  cursor: pointer;
  font-family: inherit;
}
.collapse-count {
  font-size: 10px;
  fill: #ffffff;
  font-weight: 700;
  font-family: inherit;
}
</style>
