<template>
  <div class="max-w-6xl mx-auto space-y-6">
    <!-- Page header with data-source toggle -->
    <div class="flex items-start justify-between gap-3 flex-wrap">
      <div>
        <h1 class="text-xl font-bold">{{ sourceMode === 'followup' ? '跟进记录' : '转写管理' }}</h1>
        <p class="text-sm text-muted-foreground mt-1">
          {{ sourceMode === 'followup'
            ? '从简道云同步的客户跟进记录，可批量选择进行场景/预期分析'
            : '上传会议转写，后台自动提取场景和预期，审核后写入客户档案' }}
        </p>
      </div>
      <div class="flex items-center gap-2">
        <div class="inline-flex rounded-lg border border-border p-0.5 bg-muted/30">
          <button
            class="px-3 py-1.5 text-sm font-medium rounded-md transition-colors"
            :class="sourceMode === 'transcript' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'"
            @click="toggleSourceMode('transcript')"
          >会议转写</button>
          <button
            class="px-3 py-1.5 text-sm font-medium rounded-md transition-colors"
            :class="sourceMode === 'followup' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'"
            @click="toggleSourceMode('followup')"
          >跟进记录</button>
        </div>
        <Button v-if="sourceMode === 'followup' && isSuperadmin" variant="outline" size="sm" :disabled="fetchingFollowup" @click="refreshFollowupFromJDY">
          <Loader2 v-if="fetchingFollowup" class="h-3.5 w-3.5 mr-1.5 animate-spin" />
          {{ fetchingFollowup ? '同步中...' : '刷新跟进记录' }}
        </Button>
      </div>
    </div>

    <!-- Zone A: Upload -->
    <Card v-if="sourceMode === 'transcript'" class="border-2 border-dashed border-primary/25 hover:border-primary/40 transition-colors">
      <CardHeader class="pb-2">
        <CardTitle class="text-base">上传转写文件</CardTitle>
      </CardHeader>
      <CardContent>
        <div
          class="border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all min-h-[100px]"
          :class="dragover ? 'border-primary bg-primary/5 scale-[1.01]' : 'border-muted-foreground/20 hover:border-primary/40 hover:bg-muted/50'"
          @click="triggerFileSelect"
          @dragover.prevent="dragover = true"
          @dragenter="dragover = true"
          @dragleave="dragover = false"
          @drop="handleDrop"
        >
          <div v-if="selectedFiles.length === 0" class="space-y-2">
            <Upload class="h-10 w-10 mx-auto text-muted-foreground/40" />
            <p class="text-sm font-medium text-muted-foreground">点击或拖拽文件到此处</p>
            <p class="text-xs text-muted-foreground/60">支持 .txt .srt .vtt .md .jpg .png .webp，最多 10 个文件</p>
          </div>
          <div v-else class="text-left space-y-2">
            <div v-for="(f, i) in selectedFiles" :key="i" class="flex items-center gap-3 py-2 px-3 rounded-lg bg-muted/50 border border-border/50">
              <FileText v-if="!isImageFile(f)" class="h-5 w-5 text-muted-foreground shrink-0" />
              <Image v-else class="h-5 w-5 text-muted-foreground shrink-0" />
              <span class="flex-1 text-sm truncate">{{ f.name }}</span>
              <span class="text-xs text-muted-foreground whitespace-nowrap">{{ formatFileSize(f.size) }}</span>
              <Button variant="ghost" size="icon" class="h-6 w-6 text-muted-foreground hover:text-destructive shrink-0" @click.stop="removeFile(i)">
                <X class="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </div>
        <input
          ref="fileInput"
          type="file"
          class="hidden"
          multiple
          @change="handleFileSelect"
          accept=".txt,.srt,.vtt,.md,.jpg,.jpeg,.png,.webp"
        >

        <div class="mt-4 space-y-2">
          <Label class="text-sm text-muted-foreground">手写/粘贴转写内容</Label>
          <Textarea
            v-model="manualText"
            rows="5"
            class="text-sm"
            placeholder="可直接粘贴会议转写、客户沟通纪要或零散素材"
          />
        </div>

        <div v-if="customerStore.currentCustomer" class="mt-4 flex items-center gap-2">
          <Label class="text-sm text-muted-foreground">当前客户：</Label>
          <Badge variant="secondary" class="font-medium">{{ customerStore.currentCustomer.company_name }}</Badge>
        </div>
        <Alert v-else variant="destructive" class="mt-4">
          <AlertTriangle class="h-4 w-4" />
          <span>请先在侧边栏选择一个客户</span>
        </Alert>

        <div class="mt-4">
          <Button :disabled="!canUpload || uploading" @click="uploadAndAnalyze">
            <Upload v-if="!uploading" class="h-4 w-4 mr-2" />
            <Loader2 v-else class="h-4 w-4 mr-2 animate-spin" />
            {{ uploading ? '上传中...' : '上传并开始分析' }}
          </Button>
        </div>
      </CardContent>
    </Card>

    <!-- Zone B: Table -->
    <Card>
      <CardHeader class="pb-3">
        <div class="flex items-center justify-between flex-wrap gap-2">
          <CardTitle class="text-base">{{ sourceMode === 'followup' ? '跟进记录' : '转写记录' }}</CardTitle>
          <div class="flex items-center gap-2">
            <Button
              v-if="selectedIds.size > 0"
              variant="default"
              size="sm"
              class="h-7 text-xs"
              :disabled="batchAnalyzing"
              @click="batchAnalyzeSelected"
            >
              <Loader2 v-if="batchAnalyzing" class="h-3 w-3 mr-1 animate-spin" />
              合并分析所选 ({{ selectedIds.size }})
            </Button>
            <Badge v-if="selectedIds.size > 0" variant="default">已选 {{ selectedIds.size }} 条</Badge>
            <Badge variant="secondary">{{ transcripts.length }} 条记录</Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div v-if="transcripts.length === 0" class="text-center py-12 space-y-2">
          <FileText class="h-10 w-10 mx-auto text-muted-foreground/30" />
          <p class="text-sm text-muted-foreground">{{ sourceMode === 'followup' ? '暂无跟进记录，点击右上角"刷新跟进记录"从简道云同步' : '暂无转写记录' }}</p>
        </div>
        <div v-else class="overflow-x-auto">
          <!-- Transcript mode table -->
          <table v-if="sourceMode === 'transcript'" class="w-full caption-bottom text-sm">
            <thead>
              <tr class="border-b border-border">
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[40px]">
                  <input
                    type="checkbox"
                    class="h-3.5 w-3.5 cursor-pointer accent-primary"
                    :checked="pagedTranscripts.length > 0 && pagedTranscripts.every(t => isRowSelected(t.id))"
                    @change="onToggleSelectAll($event)"
                  />
                </th>
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[16%]">标题</th>
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[10%]">客户</th>
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[7%]">类型</th>
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[11%]">状态</th>
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[12%]">提取摘要</th>
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[7%]">卡片</th>
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[13%]">时间</th>
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[16%]">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="t in pagedTranscripts"
                :key="t.id"
                class="border-b border-border/50 transition-colors hover:bg-muted/30 cursor-pointer"
                :class="{ 'bg-primary/5': selectedId === t.id }"
                @click="selectTranscript(t)"
              >
                <td class="p-3" @click.stop>
                  <input
                    type="checkbox"
                    class="h-3.5 w-3.5 cursor-pointer accent-primary"
                    :checked="isRowSelected(t.id)"
                    @change="toggleRowSelected(t.id)"
                  />
                </td>
                <td class="p-3 text-sm font-medium truncate max-w-[180px]">{{ t.title || '未命名' }}</td>
                <td class="p-3 text-sm text-muted-foreground truncate max-w-[120px]">{{ t.company_name || '-' }}</td>
                <td class="p-3">
                  <Badge variant="outline" class="text-[11px]">{{ typeLabel(t.input_type) }}</Badge>
                </td>
                <td class="p-3">
                  <StatusBadge :status="t.status || 'parsed'">{{ statusLabel(t.status) }}</StatusBadge>
                </td>
                <td class="p-3 text-sm text-muted-foreground">{{ summaryText(t.extraction_summary) }}</td>
                <td class="p-3 text-sm text-center">{{ t.card_count || 0 }}</td>
                <td class="p-3 text-xs text-muted-foreground whitespace-nowrap">{{ formatDate(t.created_at) }}</td>
                <td class="p-3">
                  <div class="flex gap-1.5">
                    <Button
                      v-if="t.status === 'parsed' || t.status === 'error'"
                      variant="outline"
                      size="sm"
                      class="h-7 text-xs"
                      :disabled="analyzingIds.has(t.id)"
                      @click.stop="triggerAnalysis(t.id)"
                    >
                      <Loader2 v-if="analyzingIds.has(t.id)" class="h-3 w-3 mr-1 animate-spin" />
                      {{ analyzingIds.has(t.id) ? '分析中' : '分析' }}
                    </Button>
                    <Button variant="ghost" size="sm" class="h-7 text-xs" @click.stop="selectTranscript(t)">详情</Button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>

          <!-- Followup mode table: simpler columns (no input_type / extraction_summary / card_count) -->
          <table v-else class="w-full caption-bottom text-sm">
            <thead>
              <tr class="border-b border-border">
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[40px]">
                  <input
                    type="checkbox"
                    class="h-3.5 w-3.5 cursor-pointer accent-primary"
                    :checked="pagedTranscripts.length > 0 && pagedTranscripts.every(t => isRowSelected(t.id))"
                    @change="onToggleSelectAll($event)"
                  />
                </th>
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[30%]">标题</th>
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[16%]">客户</th>
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[14%]">状态</th>
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[18%]">时间</th>
                <th class="h-10 px-3 text-left text-xs font-medium text-muted-foreground w-[18%]">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="t in pagedTranscripts"
                :key="t.id"
                class="border-b border-border/50 transition-colors hover:bg-muted/30 cursor-pointer"
                :class="{ 'bg-primary/5': selectedId === t.id }"
                @click="selectTranscript(t)"
              >
                <td class="p-3" @click.stop>
                  <input
                    type="checkbox"
                    class="h-3.5 w-3.5 cursor-pointer accent-primary"
                    :checked="isRowSelected(t.id)"
                    @change="toggleRowSelected(t.id)"
                  />
                </td>
                <td class="p-3 text-sm font-medium truncate max-w-[280px]">
                  <div class="flex items-center gap-2">
                    <FileText class="h-3.5 w-3.5 text-muted-foreground/60 shrink-0" />
                    <span class="truncate">{{ t.title || '未命名跟进' }}</span>
                  </div>
                </td>
                <td class="p-3 text-sm text-muted-foreground truncate max-w-[160px]">{{ t.company_name || '-' }}</td>
                <td class="p-3">
                  <StatusBadge :status="t.status || 'parsed'">{{ statusLabel(t.status) }}</StatusBadge>
                </td>
                <td class="p-3 text-xs text-muted-foreground whitespace-nowrap">{{ formatDate(t.review_date || t.created_at) }}</td>
                <td class="p-3">
                  <div class="flex gap-1.5">
                    <Button
                      v-if="t.status === 'parsed' || t.status === 'error'"
                      variant="outline"
                      size="sm"
                      class="h-7 text-xs"
                      :disabled="analyzingIds.has(t.id)"
                      @click.stop="triggerAnalysis(t.id)"
                    >
                      <Loader2 v-if="analyzingIds.has(t.id)" class="h-3 w-3 mr-1 animate-spin" />
                      {{ analyzingIds.has(t.id) ? '分析中' : '分析' }}
                    </Button>
                    <Button variant="ghost" size="sm" class="h-7 text-xs" @click.stop="selectTranscript(t)">详情</Button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Pagination -->
        <div v-if="totalPages > 1" class="flex items-center justify-between pt-4 mt-4 border-t border-border/50">
          <span class="text-xs text-muted-foreground">共 {{ transcripts.length }} 条记录</span>
          <div class="flex items-center gap-2">
            <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="currentPage <= 1" @click="goPage(currentPage - 1)">上一页</Button>
            <span class="text-xs text-muted-foreground tabular-nums">{{ currentPage }} / {{ totalPages }}</span>
            <Button variant="outline" size="sm" class="h-7 text-xs" :disabled="currentPage >= totalPages" @click="goPage(currentPage + 1)">下一页</Button>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- Zone C: Detail Panel -->
    <Card v-if="selectedTranscript" ref="detailRef">
      <CardHeader class="pb-0">
        <div class="flex items-center justify-between">
          <CardTitle class="text-base">{{ selectedTranscript.title || '转写详情' }}</CardTitle>
          <Button variant="ghost" size="icon" class="h-8 w-8" @click="selectedTranscript = null; selectedId = null">
            <X class="h-4 w-4" />
          </Button>
        </div>
        <!-- Tabs -->
        <div class="flex gap-1 mt-3 border-b border-border pb-0">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-[1px]"
            :class="activeTab === tab.key ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'"
            @click="activeTab = tab.key"
          >{{ tab.label }}</button>
        </div>
      </CardHeader>
      <CardContent class="max-h-[65vh] overflow-y-auto pt-4">
        <!-- Tab: cards -->
        <div v-if="activeTab === 'cards'">
          <div v-if="!selectedCards.length && selectedTranscript.status !== 'comparison_done'" class="text-center py-10 space-y-2">
            <Loader2 v-if="selectedTranscript.status === 'extracting' || selectedTranscript.status === 'comparing'" class="h-8 w-8 mx-auto animate-spin text-primary" />
            <FileText v-else class="h-10 w-10 mx-auto text-muted-foreground/30" />
            <p v-if="selectedTranscript.status === 'parsed'" class="text-sm text-muted-foreground">尚未分析，请先点击"分析"按钮</p>
            <p v-else-if="selectedTranscript.status === 'extracting' || selectedTranscript.status === 'comparing'" class="text-sm text-muted-foreground">分析进行中...</p>
            <p v-else class="text-sm text-muted-foreground">暂无操作卡片</p>
          </div>
          <div v-else-if="!selectedCards.length" class="text-center py-10 space-y-2">
            <FileText class="h-10 w-10 mx-auto text-muted-foreground/30" />
            <p class="text-sm text-muted-foreground">分析完成但未生成操作卡片（可能无可提取内容）</p>
          </div>

          <!-- Expectations -->
          <div v-if="cardGroups.expectations.length" class="mb-6">
            <h3 class="text-sm font-semibold mb-3 flex items-center gap-2">
              客户预期
              <Badge variant="secondary" class="text-[10px]">{{ cardGroups.expectations.length }}</Badge>
            </h3>
            <div class="space-y-3">
              <div v-for="(item, index) in cardGroups.expectations" :key="'exp-' + index"
                   class="border rounded-xl p-4 transition-colors"
                   :class="{ 'border-emerald-300 bg-emerald-50/50': item.approved, 'border-red-200 bg-red-50/40 opacity-70': item.rejected, 'border-border/60': !item.approved && !item.rejected }">
                <div class="flex justify-between items-start mb-3 flex-wrap gap-2">
                  <div class="flex items-center gap-1.5 flex-wrap">
                    <SelectNative
                      :model-value="item.status"
                      class="h-7 px-2 py-0 text-xs w-auto"
                      @update:model-value="(v) => updateExpectationField(item.operationId, 'status', v)"
                    >
                      <option value="未启动">未启动</option>
                      <option value="进行中">进行中</option>
                      <option value="已达成">已达成</option>
                      <option value="已作废">已作废</option>
                    </SelectNative>
                    <SelectNative class="h-7 px-2 py-0 text-xs w-auto" :model-value="item._targetForm || '预期表'" @update:model-value="(v) => switchCardType('expectation', index, { target: { value: v } })">
                      <option value="预期表">预期</option>
                      <option value="场景表">场景</option>
                    </SelectNative>
                    <Badge v-if="item.approved" variant="outline" class="text-[10px] bg-emerald-50 text-emerald-700 border-emerald-200">已批准</Badge>
                    <Badge v-else-if="item.rejected" variant="outline" class="text-[10px] bg-red-50 text-red-700 border-red-200">已拒绝</Badge>
                    <Badge v-else variant="outline" class="text-[10px] bg-amber-50 text-amber-700 border-amber-200">待审核</Badge>
                    <Badge v-if="item.confidence" variant="outline" class="text-[10px] bg-purple-50 text-purple-700 border-purple-200">置信度 {{ (item.confidence * 100).toFixed(0) }}%</Badge>
                    <Badge variant="outline" class="text-[10px]" :class="{
                      'bg-emerald-50 text-emerald-700 border-emerald-200': item.operationType === 'create',
                      'bg-amber-50 text-amber-700 border-amber-200': item.operationType === 'update',
                      'bg-red-50 text-red-700 border-red-200': item.operationType === 'skip',
                    }">{{ item.operationType === 'create' ? '新增' : item.operationType === 'update' ? '更新' : item.operationType === 'skip' ? '跳过' : '手动' }}</Badge>
                  </div>
                  <div class="flex gap-1 shrink-0">
                    <Button variant="outline" size="sm" class="h-7 text-xs" @click="toggleEdit('expectation', index)">编辑</Button>
                    <Button variant="outline" size="sm" class="h-7 text-xs" :class="{ 'bg-emerald-600 text-white border-emerald-600 hover:bg-emerald-700': item.approved }" @click="markCard('expectation', index, 'approve')">
                      <Check class="h-3 w-3 mr-1" />批准
                    </Button>
                    <Button variant="outline" size="sm" class="h-7 text-xs" :class="{ 'bg-red-600 text-white border-red-600 hover:bg-red-700': item.rejected }" @click="markCard('expectation', index, 'reject')">
                      <X class="h-3 w-3 mr-1" />拒绝
                    </Button>
                  </div>
                </div>
                <div class="text-sm">
                  <div v-if="isEditing('expectation', index)" class="mb-2">
                    <Label class="text-xs">标题</Label>
                    <Input
                      :model-value="item.summary"
                      class="text-sm mt-1"
                      @update:model-value="(v) => updateExpectationField(item.operationId, 'summary', v)"
                    />
                  </div>
                  <p v-else class="font-semibold mb-1.5 break-words">{{ item.summary || '未命名预期' }}</p>
                  <div v-if="isEditing('expectation', index)" class="mb-2">
                    <Label class="text-xs">描述</Label>
                    <Textarea
                      :model-value="item.description"
                      rows="2"
                      class="text-sm mt-1"
                      @update:model-value="(v) => updateExpectationField(item.operationId, 'description', v)"
                    />
                  </div>
                  <p v-else class="text-muted-foreground mb-2 break-words">{{ item.description || '暂无描述' }}</p>
                  <div class="flex items-center gap-2 mb-1">
                    <span class="text-xs text-muted-foreground">是否第一价值：</span>
                    <SelectNative
                      :model-value="item.is_first_value"
                      class="h-7 px-2 py-0 text-xs w-auto"
                      @update:model-value="(v) => updateExpectationField(item.operationId, 'is_first_value', v)"
                    >
                      <option value="是">是</option>
                      <option value="否">否</option>
                    </SelectNative>
                  </div>
                  <div v-if="item.source_quote" class="bg-muted/50 rounded-lg p-2.5 mt-2 text-xs">
                    <p class="text-muted-foreground mb-1">原文引用：</p>
                    <p class="italic break-words">"{{ item.source_quote }}"</p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Scenarios -->
          <div v-if="cardGroups.scenarios.length" class="mb-6">
            <h3 class="text-sm font-semibold mb-3 flex items-center gap-2">
              业务场景
              <Badge variant="secondary" class="text-[10px]">{{ cardGroups.scenarios.length }}</Badge>
            </h3>
            <div class="space-y-3">
              <div v-for="(item, index) in cardGroups.scenarios" :key="'scn-' + index"
                   class="border rounded-xl p-4 transition-colors"
                   :class="{ 'border-emerald-300 bg-emerald-50/50': item.approved, 'border-red-200 bg-red-50/40 opacity-70': item.rejected, 'border-border/60': !item.approved && !item.rejected }">
                <div class="flex justify-between items-start mb-3 flex-wrap gap-2">
                  <div class="flex items-center gap-1.5 flex-wrap">
                    <SelectNative class="h-7 px-2 py-0 text-xs w-auto" :model-value="item._targetForm || '场景表'" @update:model-value="(v) => switchCardType('scenario', index, { target: { value: v } })">
                      <option value="预期表">预期</option>
                      <option value="场景表">场景</option>
                    </SelectNative>
                    <Badge v-if="item.approved" variant="outline" class="text-[10px] bg-emerald-50 text-emerald-700 border-emerald-200">已批准</Badge>
                    <Badge v-else-if="item.rejected" variant="outline" class="text-[10px] bg-red-50 text-red-700 border-red-200">已拒绝</Badge>
                    <Badge v-else variant="outline" class="text-[10px] bg-amber-50 text-amber-700 border-amber-200">待审核</Badge>
                    <Badge v-if="item.confidence" variant="outline" class="text-[10px] bg-purple-50 text-purple-700 border-purple-200">置信度 {{ (item.confidence * 100).toFixed(0) }}%</Badge>
                    <Badge variant="outline" class="text-[10px]" :class="{
                      'bg-emerald-50 text-emerald-700 border-emerald-200': item.operationType === 'create',
                      'bg-amber-50 text-amber-700 border-amber-200': item.operationType === 'update',
                      'bg-red-50 text-red-700 border-red-200': item.operationType === 'skip',
                    }">{{ item.operationType === 'create' ? '新增' : item.operationType === 'update' ? '更新' : item.operationType === 'skip' ? '跳过' : '手动' }}</Badge>
                  </div>
                  <div class="flex gap-1 shrink-0">
                    <Button variant="outline" size="sm" class="h-7 text-xs" @click="toggleEdit('scenario', index)">编辑</Button>
                    <Button variant="outline" size="sm" class="h-7 text-xs" :class="{ 'bg-emerald-600 text-white border-emerald-600 hover:bg-emerald-700': item.approved }" @click="markCard('scenario', index, 'approve')">
                      <Check class="h-3 w-3 mr-1" />批准
                    </Button>
                    <Button variant="outline" size="sm" class="h-7 text-xs" :class="{ 'bg-red-600 text-white border-red-600 hover:bg-red-700': item.rejected }" @click="markCard('scenario', index, 'reject')">
                      <X class="h-3 w-3 mr-1" />拒绝
                    </Button>
                  </div>
                </div>
                <div class="text-sm">
                  <div v-if="isEditing('scenario', index)" class="mb-2">
                    <Label class="text-xs">标题</Label>
                    <Input
                      :model-value="item.title"
                      class="text-sm mt-1"
                      @update:model-value="(v) => updateScenarioField(item.operationId, 'title', v)"
                    />
                  </div>
                  <p v-else class="font-semibold mb-1.5 break-words">{{ item.title || '未命名场景' }}</p>
                  <div v-if="isEditing('scenario', index)" class="mb-2 space-y-2">
                    <div>
                      <Label class="text-xs">是否第一价值实现场景</Label>
                      <SelectNative
                        class="h-8 px-2 py-0 text-xs mt-1"
                        :model-value="item.scene_first_value"
                        @update:model-value="(v) => updateScenarioField(item.operationId, 'scene_first_value', v)"
                      >
                        <option value="">未选择</option>
                        <option value="是">是</option>
                        <option value="否">否</option>
                      </SelectNative>
                    </div>
                    <div>
                      <Label class="text-xs">解决什么问题</Label>
                      <Textarea
                        :model-value="item.question"
                        rows="3"
                        class="text-sm mt-1"
                        @update:model-value="(v) => updateScenarioField(item.operationId, 'question', v)"
                      />
                    </div>
                    <div>
                      <Label class="text-xs">怎样解决</Label>
                      <Textarea
                        :model-value="item.answer"
                        rows="3"
                        class="text-sm mt-1"
                        @update:model-value="(v) => updateScenarioField(item.operationId, 'answer', v)"
                      />
                    </div>
                    <div>
                      <Label class="text-xs">价值量化</Label>
                      <Textarea
                        :model-value="item.value_quantification"
                        rows="2"
                        class="text-sm mt-1"
                        @update:model-value="(v) => updateScenarioField(item.operationId, 'value_quantification', v)"
                      />
                    </div>
                    <div>
                      <Label class="text-xs">总结沉淀</Label>
                      <Textarea
                        :model-value="item.summary_sedimentation"
                        rows="2"
                        class="text-sm mt-1"
                        @update:model-value="(v) => updateScenarioField(item.operationId, 'summary_sedimentation', v)"
                      />
                    </div>
                    <div>
                      <Label class="text-xs">成果应用方式</Label>
                      <SelectNative
                        class="h-8 px-2 py-0 text-xs mt-1"
                        :model-value="item.application_mode"
                        @update:model-value="(v) => updateScenarioField(item.operationId, 'application_mode', v)"
                      >
                        <option value="">未选择</option>
                        <option value="挂载平台或其它系统">挂载平台或其它系统</option>
                        <option value="其他途径分享（如定时调度邮件、人工导出）">其他途径分享（如定时调度邮件、人工导出）</option>
                        <option value="个人自己使用">个人自己使用</option>
                        <option value="其他">其他</option>
                      </SelectNative>
                    </div>
                  </div>
                  <div v-else class="text-muted-foreground mb-2 break-words space-y-1">
                    <p v-if="item.scene_first_value">是否第一价值实现场景：{{ item.scene_first_value }}</p>
                    <p>解决什么问题：{{ item.question || '暂无问题描述' }}</p>
                    <p>怎样解决：{{ item.answer || '暂无解决方案' }}</p>
                    <p v-if="item.value_quantification">价值量化：{{ item.value_quantification }}</p>
                    <p v-if="item.summary_sedimentation">总结沉淀：{{ item.summary_sedimentation }}</p>
                    <p v-if="item.application_mode">成果应用方式：{{ item.application_mode }}</p>
                  </div>
                  <div class="mb-2 space-y-1.5">
                    <Label class="text-xs text-muted-foreground">关联预期</Label>
                    <SelectNative
                      class="h-8 px-2 py-0 text-xs"
                      :model-value="scenarioRelatedValue(item)"
                      @update:model-value="(v) => updateScenarioRelatedYuqi(index, v)"
                    >
                      <option value="">不关联</option>
                      <option
                        v-if="scenarioRelatedValue(item) && !hasRelatedOption(scenarioRelatedValue(item))"
                        :value="scenarioRelatedValue(item)"
                      >当前：{{ truncateLabel(item.relatedYuqiSummary || scenarioRelatedValue(item)) }}</option>
                      <optgroup v-if="relatedYuqiOptions.generated.length" label="本次生成">
                        <option v-for="opt in relatedYuqiOptions.generated" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                      </optgroup>
                      <optgroup v-if="relatedYuqiOptions.existing.length" label="已有预期">
                        <option v-for="opt in relatedYuqiOptions.existing" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                      </optgroup>
                    </SelectNative>
                    <p v-if="item.relatedYuqiReason" class="text-[10px] text-muted-foreground break-words">{{ item.relatedYuqiReason }}</p>
                    <p v-else-if="yuqiLoading" class="text-[10px] text-muted-foreground">正在加载已有预期...</p>
                    <p v-else-if="yuqiWarning" class="text-[10px] text-amber-600">{{ yuqiWarning }}</p>
                  </div>
                  <div v-if="item.source_quote" class="bg-muted/50 rounded-lg p-2.5 mt-2 text-xs">
                    <p class="text-muted-foreground mb-1">原文引用：</p>
                    <p class="italic break-words">"{{ item.source_quote }}"</p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="flex gap-2 mb-4">
            <Button variant="outline" size="sm" @click="addManualCard('预期表')">
              <Plus class="h-3.5 w-3.5 mr-1" />新增预期
            </Button>
            <Button variant="outline" size="sm" @click="addManualCard('场景表')">
              <Plus class="h-3.5 w-3.5 mr-1" />新增场景
            </Button>
          </div>

          <div v-if="cardGroups.expectations.length || cardGroups.scenarios.length" class="space-y-3">
            <div class="space-y-2.5 max-w-sm">
              <div class="flex items-center gap-2">
                <Label class="text-xs text-muted-foreground shrink-0">提交到客户：</Label>
              </div>
              <!-- Search -->
              <div class="flex gap-2">
                <Input v-model="reviewCustomerKeyword" class="flex-1 h-8 text-xs" placeholder="搜索客户" @keyup.enter="searchReviewCustomers" />
                <Button variant="secondary" size="sm" class="h-8 text-xs shrink-0" @click="searchReviewCustomers">
                  <Search class="h-3.5 w-3.5" />
                </Button>
              </div>
              <!-- Selected -->
              <div v-if="targetCompanyId" class="flex items-center justify-between bg-primary/5 border border-primary/20 rounded-lg px-3 py-2">
                <div class="flex-1 min-w-0 text-xs font-medium truncate">{{ selectedReviewCustomerName }}</div>
                <Button variant="ghost" size="sm" class="h-6 w-6 p-0 text-muted-foreground hover:text-destructive" @click="targetCompanyId = ''">
                  <X class="h-3.5 w-3.5" />
                </Button>
              </div>
              <span v-else-if="cardCustomerId && cardCustomerId !== 'demo'" class="text-[10px] text-muted-foreground">
                自动：卡片内记录 ({{ cardCustomerId.slice(0, 12) }}...)
              </span>
              <span v-else class="text-[10px] text-amber-600">
                卡片未绑定客户，请手动搜索并选择
              </span>
              <!-- Customer list -->
              <div class="rounded-lg border border-border max-h-[180px] overflow-y-auto">
                <div v-if="reviewCustomerLoading" class="text-xs text-muted-foreground py-3 text-center">搜索中...</div>
                <div v-else-if="filteredReviewCustomers.length" v-for="c in pagedReviewCustomers" :key="c.company_id"
                     class="px-3 py-2 text-xs border-b border-border/30 last:border-0 cursor-pointer hover:bg-muted/40 transition-colors"
                     :class="{ 'bg-primary/5 border-primary/20': targetCompanyId === c.company_id }"
                     @click="targetCompanyId = c.company_id">
                  <div class="font-medium truncate">{{ c.company_name }}</div>
                  <div class="text-[10px] text-muted-foreground truncate">{{ c.csm || '' }}</div>
                </div>
                <div v-else class="text-xs text-muted-foreground py-3 text-center">输入关键词搜索</div>
              </div>
              <div v-if="reviewCustomerWarning" class="text-[10px] text-destructive">{{ reviewCustomerWarning }}</div>
              <!-- Pagination -->
              <div v-if="filteredReviewCustomers.length > reviewPageSize" class="flex items-center justify-between gap-1">
                <Button variant="ghost" size="sm" class="h-6 text-[10px]" :disabled="reviewCustomerPage <= 1" @click="reviewCustomerPage--">上一页</Button>
                <span class="text-[10px] text-muted-foreground">{{ reviewCustomerPage }} / {{ Math.ceil(filteredReviewCustomers.length / reviewPageSize) }}</span>
                <Button variant="ghost" size="sm" class="h-6 text-[10px]" :disabled="reviewCustomerPage >= Math.ceil(filteredReviewCustomers.length / reviewPageSize)" @click="reviewCustomerPage++">下一页</Button>
              </div>
            </div>
            <Button :disabled="!hasApprovedCards || submitting" @click="submitCards">
              <Send v-if="!submitting" class="h-4 w-4 mr-2" />
              <Loader2 v-else class="h-4 w-4 mr-2 animate-spin" />
              {{ submitting ? '提交中...' : '提交到客户档案' }}
            </Button>
          </div>
        </div>

        <!-- Tab: raw -->
        <pre v-if="activeTab === 'raw'" class="bg-muted/50 rounded-xl p-5 text-sm leading-relaxed whitespace-pre-wrap break-words max-h-[500px] overflow-y-auto">{{ selectedTranscript.raw_text || '(无内容)' }}</pre>
      </CardContent>
    </Card>

    <!-- Toast -->
    <div v-if="message" class="fixed bottom-6 left-1/2 -translate-x-1/2 px-5 py-2.5 rounded-xl z-50 text-sm shadow-lg max-w-[90vw] break-words transition-all" :class="{
      'bg-primary text-primary-foreground': messageType === 'info',
      'bg-emerald-600 text-white': messageType === 'success',
      'bg-destructive text-destructive-foreground': messageType === 'error',
    }">{{ message }}</div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, reactive, watch } from 'vue'
import { Upload, FileText, Image, X, Check, Plus, Send, AlertTriangle, Loader2, Search } from '@lucide/vue'
import { api } from '../api'
import { useCustomerStore } from '../stores/customer'
import { uploadTranscript, startTranscriptAnalysis, fetchTranscripts, fetchTranscriptDetail } from '../api/operation'
import { fetchFollowupRecords, triggerFollowupFetch, fetchFollowupRecordDetail, startFollowupAnalysis } from '../api/followup-records'
import { reviewCard, executeCards } from '../api/operation'
import Card from '../components/ui/Card.vue'
import CardHeader from '../components/ui/CardHeader.vue'
import CardTitle from '../components/ui/CardTitle.vue'
import CardContent from '../components/ui/CardContent.vue'
import Button from '../components/ui/Button.vue'
import Input from '../components/ui/Input.vue'
import Textarea from '../components/ui/Textarea.vue'
import Label from '../components/ui/Label.vue'
import Badge from '../components/ui/Badge.vue'
import SelectNative from '../components/ui/SelectNative.vue'
import Separator from '../components/ui/Separator.vue'
import Alert from '../components/ui/Alert.vue'
import StatusBadge from '../components/StatusBadge.vue'

const customerStore = useCustomerStore()

// Data source mode: 'transcript' (default) | 'followup'
const sourceMode = ref('transcript')
const selectedIds = ref(new Set())
const fetchingFollowup = ref(false)

const isSuperadmin = computed(() => {
  try {
    const token = localStorage.getItem('zhidang_token') || ''
    const payload = JSON.parse(atob(token.split('.')[1] || '')) || {}
    return payload.source === 'superadmin'
  } catch { return false }
})

function toggleSourceMode(mode) {
  if (sourceMode.value === mode) return
  sourceMode.value = mode
  selectedId.value = null
  selectedTranscript.value = null
  loadTranscripts()
}

function selectionKey(id, mode = sourceMode.value) {
  return `${mode}:${id}`
}

function parseSelectionKey(key) {
  const [mode, ...rest] = String(key || '').split(':')
  return { mode, id: rest.join(':') }
}

function toggleRowSelected(id) {
  const next = new Set(selectedIds.value)
  const key = selectionKey(id)
  if (next.has(key)) next.delete(key); else next.add(key)
  selectedIds.value = next
}

function isRowSelected(id) { return selectedIds.value.has(selectionKey(id)) }

function onToggleSelectAll(e) {
  const checked = e.target.checked
  const next = new Set(selectedIds.value)
  for (const t of pagedTranscripts.value) {
    const key = selectionKey(t.id)
    if (checked) next.add(key); else next.delete(key)
  }
  selectedIds.value = next
}

async function refreshFollowupFromJDY() {
  if (fetchingFollowup.value) return
  fetchingFollowup.value = true
  try {
    const r = await triggerFollowupFetch()
    showMessage(`已同步：拉取 ${r.fetched} 条，新增 ${r.inserted} 条`, 'success')
    await loadTranscripts()
  } catch (e) {
    showMessage(e?.response?.data?.detail || '同步失败', 'error')
  } finally {
    fetchingFollowup.value = false
  }
}

// Zone A: Upload
const fileInput = ref(null)
const dragover = ref(false)
const selectedFiles = ref([])
const manualText = ref('')

const uploading = ref(false)
const analyzingIds = ref(new Set())
const submitting = ref(false)
const cardMarking = ref(new Set())

const canUpload = computed(() => (selectedFiles.value.length > 0 || manualText.value.trim()) && !!customerStore.currentCustomer && !uploading.value)

function triggerFileSelect() { fileInput.value.click() }

function handleFileSelect(event) {
  const files = Array.from(event.target.files || [])
  addFiles(files)
}

function handleDrop(event) {
  event.preventDefault()
  dragover.value = false
  addFiles(Array.from(event.dataTransfer.files || []))
}

function addFiles(files) {
  const allowed = ['.txt', '.srt', '.vtt', '.md', '.jpg', '.jpeg', '.png', '.webp']
  for (const f of files) {
    const suffix = '.' + (f.name.split('.').pop() || '').toLowerCase()
    if (!allowed.includes(suffix)) {
      showMessage(`不支持的文件类型: ${f.name}`, 'error')
      continue
    }
    if (selectedFiles.value.length >= 10) {
      showMessage('最多上传10个文件', 'error')
      break
    }
    selectedFiles.value.push(f)
  }
}

function removeFile(index) { selectedFiles.value.splice(index, 1) }

function isImageFile(f) {
  const suffix = '.' + (f.name.split('.').pop() || '').toLowerCase()
  return ['.jpg', '.jpeg', '.png', '.webp'].includes(suffix)
}

async function uploadAndAnalyze() {
  if (!canUpload.value || uploading.value) return
  uploading.value = true
  try {
    const companyName = customerStore.currentCustomer?.company_name || ''
    const companyId = customerStore.currentCustomer?.company_id || ''
    const files = [...selectedFiles.value]
    if (manualText.value.trim()) {
      files.push(new File([manualText.value.trim()], `手写转写-${new Date().toISOString().slice(0, 10)}.txt`, { type: 'text/plain' }))
    }
    if (files.length > 10) {
      showMessage('单次最多上传 10 份内容', 'error')
      return
    }
    const result = await uploadTranscript(files, companyName, companyId)
    selectedFiles.value = []
    manualText.value = ''
    showMessage(`创建成功，${result.file_count} 份内容已合并`, 'success')
    await triggerAnalysis(result.transcript_id)
    await loadTranscripts()
  } catch (e) {
    showMessage(e?.response?.data?.detail || '上传失败', 'error')
  } finally {
    uploading.value = false
  }
}

// Zone B: Transcript list
const transcripts = ref([])
const selectedId = ref(null)
const selectedTranscript = ref(null)
const currentPage = ref(1)
const pageSize = 5
let pollTimer = null

const totalPages = computed(() => Math.max(1, Math.ceil(transcripts.value.length / pageSize)))
const pagedTranscripts = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return transcripts.value.slice(start, start + pageSize)
})
function goPage(n) { currentPage.value = Math.max(1, Math.min(n, totalPages.value)) }

async function loadTranscripts() {
  try {
    let data
    if (sourceMode.value === 'followup') {
      const cid = customerStore.currentCustomer?.company_id || ''
      data = await fetchFollowupRecords(cid ? { company_id: cid } : {})
    } else {
      data = await fetchTranscripts()
    }
    transcripts.value = data.items || []
    currentPage.value = 1
    startPollIfNeeded()
  } catch (e) {
    console.warn('加载列表失败', e)
  }
}

const batchAnalyzing = ref(false)

async function batchAnalyzeSelected() {
  if (batchAnalyzing.value || selectedIds.value.size === 0) return
  if (!customerStore.currentCustomer) {
    showMessage('请先在侧边栏选择一个客户', 'error')
    return
  }

  batchAnalyzing.value = true
  try {
    const parts = []
    for (const key of selectedIds.value) {
      const { mode, id } = parseSelectionKey(key)
      if (!id) continue
      const detail = mode === 'followup'
        ? await fetchFollowupRecordDetail(id)
        : await fetchTranscriptDetail(id)
      const label = mode === 'followup' ? '跟进记录' : '会议转写'
      const title = detail.title || detail.company_name || id
      const raw = (detail.raw_text || '').trim()
      if (raw) {
        parts.push(`--- ${label}: ${title} ---\n${raw}`)
      }
    }
    if (!parts.length) {
      showMessage('所选记录内容为空，无法合并分析', 'error')
      return
    }
    const companyName = customerStore.currentCustomer?.company_name || ''
    const companyId = customerStore.currentCustomer?.company_id || ''
    const mergedText = parts.join('\n\n')
    const mergedFile = new File([mergedText], `合并分析-${new Date().toISOString().slice(0, 10)}.txt`, { type: 'text/plain' })
    const result = await uploadTranscript([mergedFile], companyName, companyId)
    showMessage(`已合并 ${parts.length} 条记录并启动分析`, 'success')
    selectedIds.value = new Set()
    sourceMode.value = 'transcript'
    await triggerAnalysis(result.transcript_id)
    await loadTranscripts()
  } catch (e) {
    console.warn('合并分析失败', e)
    showMessage(e?.response?.data?.detail || '合并分析失败', 'error')
  } finally {
    batchAnalyzing.value = false
  }
}

async function analyzeExistingRecord(t) {
  if (!t || analyzingIds.value.has(t.id)) return
  analyzingIds.value.add(t.id)
  try {
    if (sourceMode.value === 'followup') {
      await startFollowupAnalysis(t.id)
    } else {
      await startTranscriptAnalysis(t.id)
    }
    showMessage('分析已启动，可关闭页面稍后查看', 'success')
    await loadTranscripts()
  } catch (e) {
    showMessage(e?.response?.data?.detail || '启动分析失败', 'error')
  } finally {
    analyzingIds.value.delete(t.id)
  }
}

async function analyzeUploadedTranscript(transcriptId) {
  if (analyzingIds.value.has(transcriptId)) return
  analyzingIds.value.add(transcriptId)
  try {
    await startTranscriptAnalysis(transcriptId)
    showMessage('分析已启动，可关闭页面稍后查看', 'success')
    await loadTranscripts()
  } catch (e) {
    showMessage(e?.response?.data?.detail || '启动分析失败', 'error')
  } finally {
    analyzingIds.value.delete(transcriptId)
  }
}

async function triggerAnalysis(transcriptId) {
  const row = transcripts.value.find(t => t.id === transcriptId)
  if (row) {
    await analyzeExistingRecord(row)
  } else {
    await analyzeUploadedTranscript(transcriptId)
  }
}

function startPollIfNeeded() {
  const hasProcessing = transcripts.value.some(t => ['extracting', 'comparing'].includes(t.status))
  if (hasProcessing && !pollTimer) {
    pollTimer = setInterval(loadTranscripts, 5000)
  } else if (!hasProcessing && pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const detailRef = ref(null)

async function selectTranscript(t) {
  selectedId.value = t.id
  try {
    selectedTranscript.value = sourceMode.value === 'followup'
      ? await fetchFollowupRecordDetail(t.id)
      : await fetchTranscriptDetail(t.id)
    activeTab.value = 'cards'
    loadCardsFromTranscript()
    setTimeout(() => detailRef.value?.$el?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }), 100)
  } catch (e) {
    showMessage('加载详情失败', 'error')
  }
}

function statusLabel(s) {
  const map = { parsed: '待分析', extracting: '提取中', extraction_done: '已提取', comparing: '比对中', comparison_done: '待审核', reviewed: '已完成', error: '失败' }
  return map[s] || s || '未知'
}

function typeLabel(t) { return t === 'image' ? '图片' : t === 'mixed' ? '混合' : '文本' }

function summaryText(s) {
  if (!s) return '-'
  return `预期${s.expectations || 0} / 场景${s.scenarios || 0}`
}

function formatDate(d) {
  if (!d) return '-'
  return new Date(d).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

// Zone C: Detail panel
const activeTab = ref('cards')
const tabs = [
  { key: 'cards', label: '场景和预期' },
  { key: 'raw', label: '原始转写' },
]

const selectedCards = ref([])
const editingItems = ref(new Set())
const reviewState = reactive(new Map())  // card_id -> 'approved' | 'rejected'

const cardGroups = computed(() => {
  const expectations = []
  const scenarios = []
  for (const card of selectedCards.value) {
    const tf = card._targetForm || card.target_form || ''
    const items = card.change_items || []
    const getVal = (name) => {
      const ci = items.find(i => i.field_name === name || i.widget_name === name)
      return ci ? ci.new_value : ''
    }
    const item = {
      summary: getVal('预期简述') || getVal('detail_brief'),
      scene_first_value: tf === '场景表' ? (getVal('是否第一价值实现场景') || '') : '',
      question: tf === '场景表' ? (getVal('解决什么问题') || getVal('solve_what_ques') || '') : '',
      answer: tf === '场景表' ? (getVal('怎样解决') || getVal('solve_what_ans') || '') : '',
      value_quantification: tf === '场景表' ? (getVal('价值量化') || '') : '',
      summary_sedimentation: tf === '场景表' ? (getVal('总结沉淀') || '') : '',
      application_mode: tf === '场景表' ? (getVal('成果应用方式') || '') : '',
      description: tf === '场景表' ? '' : (getVal('预期详情') || getVal('detail')),
      title: getVal('场景标题') || getVal('title'),
      status: (() => {
        const v = getVal('预期状态') || getVal('yuqi_status') || '未启动'
        return ['未启动', '进行中', '已达成', '已作废'].includes(v) ? v : '未启动'
      })(),
      is_first_value: tf === '场景表' ? (getVal('是否第一价值实现场景') || '') : (getVal('是否第一价值实现预期') || '否'),
      confidence: card.confidence || 0,
      source_quote: card.source_quote || '',
      operationId: card.card_id,
      operationType: card.operation_type || 'create',
      approved: reviewState.get(card.card_id) === 'approved',
      rejected: reviewState.get(card.card_id) === 'rejected',
      customerId: card.customer_id || '',
      _targetForm: tf,
      relatedYuqiId: card.related_yuqi_id || '',
      relatedYuqiCardId: card.related_yuqi_card_id || '',
      relatedYuqiSource: card.related_yuqi_card_id ? 'generated' : (card.related_yuqi_id ? 'existing' : ''),
      relatedYuqiSummary: card.related_yuqi_summary || '',
      relatedYuqiReason: card.related_yuqi_reason || '',
    }
    if (tf === '预期表') expectations.push(item)
    else if (tf === '场景表') scenarios.push(item)
  }
  return { expectations, scenarios }
})

const hasApprovedCards = computed(() => {
  return [...cardGroups.value.expectations, ...cardGroups.value.scenarios].some(c => c.approved)
})

const cardCustomerId = computed(() => {
  const allCards = [...cardGroups.value.expectations, ...cardGroups.value.scenarios]
  const firstId = allCards.find(c => c.customerId && c.customerId !== 'demo')?.customerId
  if (firstId) return firstId
  return customerStore.currentCustomer?.company_id || ''
})
const targetCompanyId = ref('')
const effectiveCompanyId = computed(() => targetCompanyId.value || cardCustomerId.value)
const reviewCustomerKeyword = ref('')
const reviewCustomerPage = ref(1)
const reviewPageSize = 20
const reviewCustomerLoading = ref(false)
const reviewCustomerWarning = ref('')
const reviewSearchResults = ref([])  // remote search results, separate from customerStore.customers
const filteredReviewCustomers = computed(() => {
  const k = reviewCustomerKeyword.value.trim().toLowerCase()
  // 有搜索关键词时用远程结果（已在 searchReviewCustomers 中筛选），否则用本地列表
  if (k && reviewSearchResults.value.length > 0) return reviewSearchResults.value
  if (!k) return customerStore.customers
  return customerStore.customers.filter(c => c.company_name.toLowerCase().includes(k))
})
const selectedReviewCustomerName = computed(() => {
  if (!targetCompanyId.value) return ''
  const all = [...customerStore.customers, ...reviewSearchResults.value]
  const found = all.find(c => c.company_id === targetCompanyId.value)
  return found?.company_name || targetCompanyId.value.slice(0, 12) + '...'
})
const pagedReviewCustomers = computed(() => {
  const start = (reviewCustomerPage.value - 1) * reviewPageSize
  return filteredReviewCustomers.value.slice(start, start + reviewPageSize)
})

const yuqiLoading = ref(false)
const yuqiWarning = ref('')
const customerYuqiItems = ref([])

function truncateLabel(text, limit = 32) {
  const value = String(text || '').trim()
  return value.length <= limit ? value : value.slice(0, limit) + '...'
}

function yuqiSummary(row) {
  return String(row?.detail_brief || row?.['预期简述'] || row?.detail || row?._id || '').trim()
}

const relatedYuqiOptions = computed(() => {
  const generated = cardGroups.value.expectations.map(item => ({
    value: `card:${item.operationId}`,
    label: `本次生成：${truncateLabel(item.summary || item.operationId)}`,
    summary: item.summary || '',
    cardId: item.operationId,
  }))
  const existing = customerYuqiItems.value
    .filter(row => row && row._id)
    .map(row => ({
      value: `existing:${row._id}`,
      label: `已有：${truncateLabel(yuqiSummary(row) || row._id)}`,
      summary: yuqiSummary(row),
      id: row._id,
    }))
  return { generated, existing }
})

function scenarioRelatedValue(item) {
  if (item.relatedYuqiCardId) return `card:${item.relatedYuqiCardId}`
  if (item.relatedYuqiId) return `existing:${item.relatedYuqiId}`
  return ''
}

function findRelatedOption(value) {
  return [...relatedYuqiOptions.value.generated, ...relatedYuqiOptions.value.existing].find(opt => opt.value === value)
}

function hasRelatedOption(value) {
  return !!findRelatedOption(value)
}

function updateScenarioRelatedYuqi(index, value) {
  const item = cardGroups.value.scenarios[index]
  if (!item) return
  const card = selectedCards.value.find(c => c.card_id === item.operationId)
  if (!card) return
  const opt = findRelatedOption(value)
  card.related_yuqi_summary = opt?.summary || ''
  card.related_yuqi_reason = value ? '人工审核选择' : ''
  if (!value) {
    card.related_yuqi_id = ''
    card.related_yuqi_card_id = ''
    card.related_yuqi_source = ''
  } else if (value.startsWith('existing:')) {
    card.related_yuqi_id = value.slice('existing:'.length)
    card.related_yuqi_card_id = ''
    card.related_yuqi_source = 'existing'
  } else if (value.startsWith('card:')) {
    card.related_yuqi_id = ''
    card.related_yuqi_card_id = value.slice('card:'.length)
    card.related_yuqi_source = 'generated'
  }
}

function findSelectedCard(cardId) {
  return selectedCards.value.find(c => c.card_id === cardId)
}

function upsertChangeItem(card, fieldName, widgetName, value) {
  if (!card) return
  const items = [...(card.change_items || [])]
  let item = items.find(i => i.field_name === fieldName || i.widget_name === widgetName)
  if (!item) {
    item = { field_name: fieldName, widget_name: widgetName, old_value: null, new_value: '' }
    items.push(item)
  }
  item.field_name = fieldName
  item.widget_name = widgetName
  item.new_value = value ?? ''
  card.change_items = items
}

function splitScenarioDescription(value) {
  const text = String(value ?? '').trim()
  const marker = ' — '
  if (!text.includes(marker)) {
    return { question: text, answer: '' }
  }
  const [question, ...rest] = text.split(marker)
  return { question: question.trim(), answer: rest.join(marker).trim() }
}

function updateExpectationField(cardId, field, value) {
  const card = findSelectedCard(cardId)
  if (!card) return
  const valueText = String(value ?? '')
  if (field === 'summary') {
    upsertChangeItem(card, '预期简述', 'detail_brief', valueText)
  } else if (field === 'description') {
    upsertChangeItem(card, '预期详情', 'detail', valueText)
  } else if (field === 'status') {
    const allowed = new Set(['未启动', '进行中', '已达成', '已作废'])
    upsertChangeItem(card, '预期状态', 'yuqi_status', allowed.has(valueText) ? valueText : '未启动')
  } else if (field === 'is_first_value') {
    upsertChangeItem(card, '是否第一价值实现预期', 'is_first_value', valueText)
  }
}

function updateScenarioField(cardId, field, value) {
  const card = findSelectedCard(cardId)
  if (!card) return
  const valueText = String(value ?? '')
  if (field === 'title') {
    upsertChangeItem(card, '场景标题', 'title', valueText)
  } else if (field === 'scene_first_value') {
    upsertChangeItem(card, '是否第一价值实现场景', '_widget_1744337240628', valueText)
  } else if (field === 'question') {
    upsertChangeItem(card, '解决什么问题', 'solve_what_ques', valueText)
  } else if (field === 'answer') {
    upsertChangeItem(card, '怎样解决', 'solve_what_ans', valueText)
  } else if (field === 'value_quantification') {
    upsertChangeItem(card, '价值量化', '_widget_1773296816191', valueText)
  } else if (field === 'summary_sedimentation') {
    upsertChangeItem(card, '总结沉淀', '_widget_1773296816192', valueText)
  } else if (field === 'application_mode') {
    upsertChangeItem(card, '成果应用方式', '_widget_1737340360281', valueText)
  } else if (field === 'description') {
    const { question, answer } = splitScenarioDescription(valueText)
    upsertChangeItem(card, '解决什么问题', 'solve_what_ques', question)
    upsertChangeItem(card, '怎样解决', 'solve_what_ans', answer)
  }
}

async function loadCustomerYuqiOptions(companyId) {
  const id = String(companyId || '').trim()
  if (!id || id === 'demo') {
    customerYuqiItems.value = []
    yuqiWarning.value = ''
    return
  }
  yuqiLoading.value = true
  try {
    const resp = await api.get(`/api/v1/customers/${id}/yuqi`, { params: { limit: 100 } })
    customerYuqiItems.value = resp.data?.items || []
    yuqiWarning.value = resp.data?.warning || ''
  } catch (e) {
    customerYuqiItems.value = []
    yuqiWarning.value = e?.response?.data?.detail || '已有预期加载失败'
  } finally {
    yuqiLoading.value = false
  }
}

watch(effectiveCompanyId, (id) => {
  loadCustomerYuqiOptions(id)
})

async function searchReviewCustomers() {
  reviewCustomerPage.value = 1
  const keyword = reviewCustomerKeyword.value.trim()
  if (!keyword) {
    reviewSearchResults.value = []
    reviewCustomerWarning.value = ''
    return
  }
  reviewCustomerLoading.value = true
  try {
    const data = await customerStore.searchCustomersRemote(keyword)
    reviewSearchResults.value = data.customers || []
    reviewCustomerWarning.value = data.warning || ''
  } catch (e) {
    reviewCustomerWarning.value = e?.response?.data?.detail || '搜索失败'
    reviewSearchResults.value = []
  } finally {
    reviewCustomerLoading.value = false
  }
}

function safeUUID() {
  try { return crypto.randomUUID() } catch { return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random()*16|0; return (c==='x'?r:r&0x3|0x8).toString(16) }) }
}

function loadCardsFromTranscript() {
  const t = selectedTranscript.value
  if (!t) return
  const cards = (t.agent_b_result || {}).result?.operation_cards || []
  selectedCards.value = cards.map(c => ({ ...c, _targetForm: c.target_form }))
  editingItems.value = new Set()
  // 从 DB 恢复审核状态
  for (const c of cards) {
    if (c.review_status === 'approved' || c.review_status === 'rejected') {
      reviewState.set(c.card_id, c.review_status)
    }
  }
  // 卡片未绑定客户时默认选中侧边栏当前客户
  if (!targetCompanyId.value) {
    const firstValid = cards.find(c => c.customer_id && c.customer_id !== 'demo')
    if (!firstValid && customerStore.currentCustomer?.company_id) {
      targetCompanyId.value = customerStore.currentCustomer.company_id
    }
  }
  loadCustomerYuqiOptions(effectiveCompanyId.value)
}

async function addManualCard(targetForm) {
  const cardId = safeUUID()
  const changeItems = targetForm === '预期表'
    ? [
        { field_name: '预期简述', widget_name: 'detail_brief', new_value: '' },
        { field_name: '预期详情', widget_name: 'detail', new_value: '' },
        { field_name: '预期状态', widget_name: 'yuqi_status', new_value: '未启动' },
        { field_name: '是否第一价值实现预期', widget_name: 'is_first_value', new_value: '否' },
      ]
    : [
        { field_name: '场景标题', widget_name: 'title', new_value: '' },
        { field_name: '是否第一价值实现场景', widget_name: '_widget_1744337240628', new_value: '' },
        { field_name: '解决什么问题', widget_name: 'solve_what_ques', new_value: '' },
        { field_name: '怎样解决', widget_name: 'solve_what_ans', new_value: '' },
        { field_name: '价值量化', widget_name: '_widget_1773296816191', new_value: '' },
        { field_name: '总结沉淀', widget_name: '_widget_1773296816192', new_value: '' },
        { field_name: '成果应用方式', widget_name: '_widget_1737340360281', new_value: '' },
      ]
  const newCard = {
    card_id: cardId,
    target_form: targetForm,
    _targetForm: targetForm,
    operation_type: 'create',
    operationType: 'create',
    change_items: changeItems,
    confidence: 0,
    source_quote: '',
    review_status: 'approved',
    approved: true,
    rejected: false,
    _manual: true,
  }
  try {
    await api.post('/api/v1/operations/add', {
      transcript_id: selectedId.value,
      card: {
        card_id: cardId,
        target_form: targetForm,
        operation_type: 'create',
        change_items: changeItems,
      },
    })
  } catch (e) { console.warn('添加卡片到后端失败:', e) }
  selectedCards.value.push(newCard)
  reviewState.set(cardId, 'approved')
}

function switchCardType(type, index, event) {
  const newTarget = typeof event === 'string' ? event : event?.target?.value
  if (!newTarget) return
  const list = cardGroups.value[type === 'expectation' ? 'expectations' : 'scenarios']
  if (!list || !list[index]) return
  const item = list[index]
  const oldTarget = item._targetForm
  if (oldTarget === newTarget) return
  item._targetForm = newTarget
  for (const card of selectedCards.value) {
    if (card.card_id === item.operationId || (card._manual && card.card_id === item.operationId)) {
      card.target_form = newTarget
      card._targetForm = newTarget
      // 重新映射 change_items：找到旧表单的字段值，写入新表单的对应字段
      const items = card.change_items || []
      const getVal = (name) => {
        const ci = items.find(i => i.field_name === name || i.widget_name === name)
        return ci ? ci.new_value : ''
      }
      const newItems = []
      if (oldTarget === '场景表' && newTarget === '预期表') {
        const title = getVal('场景标题') || getVal('title')
        const ques = getVal('解决什么问题') || getVal('solve_what_ques')
        const ans  = getVal('怎样解决') || getVal('solve_what_ans')
        const desc = [ques, ans].filter(Boolean).join('；')
        if (title) newItems.push({ field_name: '预期简述', widget_name: 'detail_brief', new_value: title })
        if (desc) newItems.push({ field_name: '预期详情', widget_name: 'detail', new_value: desc })
      } else if (oldTarget === '预期表' && newTarget === '场景表') {
        const brief = getVal('预期简述') || getVal('detail_brief')
        const detail = getVal('预期详情') || getVal('detail')
        if (brief) newItems.push({ field_name: '场景标题', widget_name: 'title', new_value: brief })
        if (detail) newItems.push({ field_name: '解决什么问题', widget_name: 'solve_what_ques', new_value: detail })
        newItems.push({ field_name: '是否第一价值实现场景', widget_name: '_widget_1744337240628', new_value: '' })
        newItems.push({ field_name: '价值量化', widget_name: '_widget_1773296816191', new_value: '' })
        newItems.push({ field_name: '总结沉淀', widget_name: '_widget_1773296816192', new_value: '' })
        newItems.push({ field_name: '成果应用方式', widget_name: '_widget_1737340360281', new_value: '' })
      }
      card.change_items = newItems
      break
    }
  }
}

function isEditing(type, index) { return editingItems.value.has(`${type}_${index}`) }

function toggleEdit(type, index) {
  const key = `${type}_${index}`
  if (editingItems.value.has(key)) editingItems.value.delete(key)
  else editingItems.value.add(key)
}

async function markCard(type, index, action) {
  const item = cardGroups.value[type === 'expectation' ? 'expectations' : 'scenarios'][index]
  if (!item) return
  const key = `${type}_${index}_${action}`
  if (cardMarking.value.has(key)) return
  cardMarking.value.add(key)
  if (action === 'approve') { item.approved = true; item.rejected = false; reviewState.set(item.operationId, 'approved') }
  else { item.approved = false; item.rejected = true; reviewState.set(item.operationId, 'rejected') }
  try {
    await reviewCard({
      transcript_id: selectedId.value,
      card_id: item.operationId,
      action: action,
    })
  } catch (e) { console.warn('同步审核状态失败', e) }
  cardMarking.value.delete(key)
}

async function submitCards() {
  if (submitting.value) return
  const allApproved = [...cardGroups.value.expectations, ...cardGroups.value.scenarios].filter(c => c.approved)
  const approved = allApproved.map(c => c.operationId)
  if (!approved.length) return
  const approvedSet = new Set(approved)
  const brokenRelation = allApproved.find(c => c._targetForm === '场景表' && c.relatedYuqiCardId && !approvedSet.has(c.relatedYuqiCardId))
  if (brokenRelation) {
    showMessage('场景关联了本次生成的预期，请先批准对应预期卡片', 'error')
    return
  }
  // 收集 UI 中用户修改过的字段值
  const fieldUpdates = {}
  const cardOverrides = {}
  for (const item of allApproved) {
    const up = {}
    if (item._targetForm === '预期表') {
      up['预期简述'] = item.summary || ''
      up['预期详情'] = item.description || ''
      if (item.status) up['预期状态'] = item.status
      if (item.is_first_value) up['是否第一价值实现预期'] = item.is_first_value
    } else if (item._targetForm === '场景表') {
      up['场景标题'] = item.title || ''
      if (item.scene_first_value) up['是否第一价值实现场景'] = item.scene_first_value
      up['解决什么问题'] = item.question || splitScenarioDescription(item.description || '').question
      up['怎样解决'] = item.answer || splitScenarioDescription(item.description || '').answer
      if (item.value_quantification) up['价值量化'] = item.value_quantification
      if (item.summary_sedimentation) up['总结沉淀'] = item.summary_sedimentation
      if (item.application_mode) up['成果应用方式'] = item.application_mode
    }
    if (Object.keys(up).length) fieldUpdates[item.operationId] = up
    // 始终带 target_form，后端用它覆盖 OPERATION_CARD_STORE 中的旧值
    const override = { target_form: item._targetForm }
    if (item._targetForm === '场景表') {
      override.related_yuqi_id = item.relatedYuqiId || ''
      override.related_yuqi_card_id = item.relatedYuqiCardId || ''
      override.related_yuqi_source = item.relatedYuqiCardId ? 'generated' : (item.relatedYuqiId ? 'existing' : '')
      override.related_yuqi_summary = item.relatedYuqiSummary || ''
      override.related_yuqi_reason = item.relatedYuqiReason || ''
    }
    cardOverrides[item.operationId] = override
  }
  submitting.value = true
  try {
    const resp = await executeCards(
      { transcript_id: selectedId.value, card_ids: approved, field_updates: fieldUpdates, card_overrides: cardOverrides },
      effectiveCompanyId.value
    )
    const results = resp.results || []
    const ok = results.filter(r => r.execute_status === 'success').length
    const fail = results.length - ok
    showMessage(`提交完成：成功 ${ok}，失败 ${fail}`, ok > 0 ? 'success' : 'error')
  } catch (e) {
    showMessage(e?.response?.data?.detail || '提交失败', 'error')
  } finally {
    submitting.value = false
  }
}

// Followup
const followupGenerating = ref(false)
const followupSubmitting = ref(false)
const followupData = ref(null)
const followupTagTree = ref([])

async function loadTagTree() {
  try {
    const resp = await api.get('/api/v1/followup/tags')
    followupTagTree.value = resp.data?.tags || resp.data?.tag_tree || []
  } catch {}
}

async function generateFollowup() {
  if (!selectedTranscript.value) return
  followupGenerating.value = true
  try {
    const resp = await api.post('/api/v1/followup/generate', {
      input_type: selectedTranscript.value.input_type || 'text',
      content: selectedTranscript.value.raw_text || '',
      company_id: selectedTranscript.value.company_id || customerStore.currentCustomer?.company_id || 'demo',
      company_name: selectedTranscript.value.company_name || customerStore.currentCustomer?.company_name || '',
    })
    if (resp.data?.error) throw new Error(resp.data.error)
    followupData.value = resp.data
    showMessage('跟进记录生成完成', 'success')
  } catch (e) {
    showMessage(e?.response?.data?.detail || '生成跟进记录失败', 'error')
  } finally {
    followupGenerating.value = false
  }
}

async function submitFollowup() {
  if (!followupData.value) return
  followupSubmitting.value = true
  try {
    await api.post('/api/v1/followup/submit', {
      ...followupData.value,
      company_id: selectedTranscript.value?.company_id || customerStore.currentCustomer?.company_id || 'demo',
      company_name: selectedTranscript.value?.company_name || customerStore.currentCustomer?.company_name || '',
    })
    showMessage('跟进记录已提交', 'success')
    followupData.value = null
  } catch (e) {
    showMessage(e?.response?.data?.detail || '提交跟进记录失败', 'error')
  } finally {
    followupSubmitting.value = false
  }
}

// Common
const message = ref('')
const messageType = ref('info')

function showMessage(msg, type = 'info') {
  message.value = msg
  messageType.value = type
  setTimeout(() => { message.value = '' }, 4000)
}

function formatFileSize(bytes) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

watch(() => customerStore.currentCustomer?.company_id, (id, prev) => {
  if (id === prev) return
  if (sourceMode.value === 'followup') {
    selectedIds.value = new Set()
    selectedId.value = null
    selectedTranscript.value = null
    loadTranscripts()
  }
})

onMounted(async () => {
  customerStore.hydrateCurrentCustomer()
  await customerStore.fetchCustomers()
  await loadTagTree()
  await loadTranscripts()
})

onUnmounted(() => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
})
</script>
