<script setup lang="ts">
import type {Attempt} from '../types/domain';
import {statuses,stages} from '../constants/enums';
import {dateTime} from '../utils/format';
import StatusBadge from './common/StatusBadge.vue';
defineProps<{attempts:Attempt[]}>();
const stageText=(s:string)=>stages[s]||s;
</script>
<template>
  <div class="attempt-list">
    <article v-for="a in [...attempts].reverse()" :key="a.id" class="attempt" :class="a.status">
      <header>
        <span class="attempt-no">第 {{a.attempt_no}} 次尝试</span>
        <StatusBadge :status="a.status"/>
      </header>
      <div class="progress-track" :aria-label="'第'+a.attempt_no+'次尝试进度'">
        <div class="progress-fill" :class="a.status" :style="{width:(a.status==='completed'?100:a.progress)+'%'}"></div>
      </div>
      <p class="attempt-line">
        <b>{{stageText(a.stage)}}</b>
        <span v-if="a.status==='running'||a.status==='queued'"> · {{a.progress}}%</span>
      </p>
      <p v-if="a.detail" class="attempt-detail">{{a.detail}}</p>
      <p v-if="a.error" class="attempt-error">原因：{{a.error}}</p>
      <footer>
        <span v-if="a.started_at">开始 {{dateTime(a.started_at)}}</span>
        <span v-if="a.finished_at">结束 {{dateTime(a.finished_at)}}</span>
        <span v-if="!a.started_at && a.created_at">建队 {{dateTime(a.created_at)}}</span>
      </footer>
    </article>
  </div>
</template>
