<script setup lang="ts">
import type {Run} from '../types/domain';
import StatusBadge from './common/StatusBadge.vue';
import {number,date} from '../utils/format';
import {stages} from '../constants/enums';
const props=defineProps<{runs:Run[];busy?:boolean}>();
const emit=defineEmits<{(e:'cancel',id:number):void;(e:'retry',id:number):void}>();
const active=(r:Run)=>[...r.attempts].reverse().find(a=>['queued','running'].includes(a.status));
const stageText=(s:string)=>stages[s]||s;
function statusReason(r:Run):string{
  const withError=[...r.attempts].reverse().find(a=>a.error);
  const last=r.attempts[r.attempts.length-1];
  if(r.status==='cancelled')return withError||last?'已取消，结果未封存':'已取消';
  return withError?.error?('失败：'+withError.error):'未完成';
}
</script>
<template>
  <div class="table-wrap"><table><thead><tr><th>研究名称</th><th>状态</th><th>特征 / 候选</th><th>分组CV MAE</th><th>封存MAE</th><th>尝试与进度</th><th></th></tr></thead><tbody>
    <tr v-for="r in props.runs" :key="r.id">
      <td><b>{{r.name}}</b><small>{{date(r.created_at)}} · 共{{r.attempt_count}}次尝试</small></td>
      <td><StatusBadge :status="r.status"/></td>
      <td>{{r.config.features.length}} / {{r.config.alphas.length*r.config.l1_ratios.length}}</td>
      <td>{{number(r.result.best?.mean_mae,2)}}</td>
      <td>{{number(r.result.metrics?.mae,2)}}</td>
      <td class="progress-cell">
        <template v-if="active(r)">
          <div class="progress-track small"><div class="progress-fill" :class="active(r)!.status" :style="{width:active(r)!.progress+'%'}"></div></div>
          <small>{{stageText(active(r)!.stage)}} · {{active(r)!.progress}}%（第{{active(r)!.attempt_no}}次）</small>
        </template>
        <small v-else-if="r.status==='failed'||r.status==='cancelled'" class="muted">{{statusReason(r)}}</small>
        <small v-else class="muted">第{{r.attempt_count}}次尝试完成</small>
      </td>
      <td class="row-actions">
        <RouterLink :to="'/drivers?run='+r.id">读取驱动解释 ↗</RouterLink>
        <button v-if="['queued','running'].includes(r.status)" class="text-button danger" :disabled="props.busy" @click="emit('cancel',r.id)">取消研究</button>
        <button v-if="['failed','cancelled'].includes(r.status)" class="text-button" :disabled="props.busy" @click="emit('retry',r.id)">失败重试 ↻</button>
      </td>
    </tr>
  </tbody></table></div>
</template>
