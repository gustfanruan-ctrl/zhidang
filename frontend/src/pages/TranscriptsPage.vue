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
            <p class="text-xs text-muted-foreground/60">支持 .txt .srt .vtt .md .pdf .doc .docx .jpg .png .webp，最多 10 个文件</p>
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
          accept=".txt,.srt,.vtt,.md,.pdf,.doc,.docx,.jpg,.jpeg,.png,.webp"
        >

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
              分析所选 ({{ selectedIds.size }})
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
                    <SelectNative v-model="item.status" class="h-7 px-2 py-0 text-xs w-auto">
                      <option value="未启动">未启动</option>
                      <option value="进行中">进行中</option>
                      <option value="已达成">已达成</option>
                      <option value="已作废">已作废</option>
                    </SelectNative>
                    <SelectNative class="h-7 px-2 py-0 text-xs w-auto" :model-value="item._targetForm || '预期表'" @update:model-value="(v) => switchCardType('expectation', index, { target: { value: v } })">
                      <option value="预期表">预期</option>
                      <option value="场景表">场景</option>
                    </SelectNative>
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
                    <Input v-model="item.summary" class="text-sm mt-1" />
                  </div>
                  <p v-else class="font-semibold mb-1.5 break-words">{{ item.summary || '未命名预期' }}</p>
                  <div v-if="isEditing('expectation', index)" class="mb-2">
                    <Label class="text-xs">描述</Label>
                    <Textarea v-model="item.description" rows="2" class="text-sm mt-1" />
                  </div>
                  <p v-else class="text-muted-foreground mb-2 break-words">{{ item.description || '暂无描述' }}</p>
                  <div class="flex items-center gap-2 mb-1">
                    <span class="text-xs text-muted-foreground">是否第一价值：</span>
                    <SelectNative v-model="item.is_first_value" class="h-7 px-2 py-0 text-xs w-auto">
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
                    <Input v-model="item.title" class="text-sm mt-1" />
                  </div>
                  <p v-else class="font-semibold mb-1.5 break-words">{{ item.title || '未命名场景' }}</p>
                  <div v-if="isEditing('scenario', index)" class="mb-2">
                    <Label class="text-xs">描述</Label>
                    <Textarea v-model="item.description" rows="2" class="text-sm mt-1" />
                  </div>
                  <p v-else class="text-muted-foreground mb-2 break-words">{{ item.description || '暂无描述' }}</p>
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

          <div v-if="cardGroups.expectations.length || cardGroups.scenarios.length">
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
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Upload, FileText, Image, X, Check, Plus, Send, AlertTriangle, Loader2 } from '@lucide/vue'
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
  selectedIds.value = new Set()
  selectedId.value = null
  selectedTranscript.value = null
  loadTranscripts()
}

function toggleRowSelected(id) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  selectedIds.value = next
}

function isRowSelected(id) { return selectedIds.value.has(id) }

function onToggleSelectAll(e) {
  const checked = e.target.checked
  const next = new Set(selectedIds.value)
  for (const t of pagedTranscripts.value) {
    if (checked) next.add(t.id); else next.delete(t.id)
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

const uploading = ref(false)
const analyzingIds = ref(new Set())
const submitting = ref(false)
const cardMarking = ref(new Set())

const canUpload = computed(() => selectedFiles.value.length > 0 && !!customerStore.currentCustomer && !uploading.value)

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
  const allowed = ['.txt', '.srt', '.vtt', '.md', '.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png', '.webp']
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
    const result = await uploadTranscript(selectedFiles.value, companyName)
    selectedFiles.value = []
    showMessage(`上传成功，${result.file_count} 个文件已合并`, 'success')
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
  const ids = [...selectedIds.value]
  const eligible = transcripts.value.filter(t => ids.includes(t.id) && (t.status === 'parsed' || t.status === 'error'))
  if (eligible.length === 0) {
    showMessage('所选记录均不可分析（仅"待分析"或"失败"状态可触发）', 'error')
    return
  }
  if (eligible.length < ids.length) {
    showMessage(`已跳过 ${ids.length - eligible.length} 条不可分析的记录`, 'info')
  }
  batchAnalyzing.value = true
  let ok = 0, fail = 0
  for (const t of eligible) {
    try {
      if (sourceMode.value === 'followup') {
        await startFollowupAnalysis(t.id)
      } else {
        await startTranscriptAnalysis(t.id)
      }
      ok += 1
    } catch (e) {
      fail += 1
      console.warn('分析触发失败', t.id, e)
    }
  }
  batchAnalyzing.value = false
  showMessage(`已触发 ${ok} 条分析${fail ? `，失败 ${fail}` : ''}`, ok > 0 ? 'success' : 'error')
  selectedIds.value = new Set()
  await loadTranscripts()
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

async function triggerAnalysis(transcriptId) {
  if (analyzingIds.value.has(transcriptId)) return
  analyzingIds.value.add(transcriptId)
  try {
    if (sourceMode.value === 'followup') {
      await startFollowupAnalysis(transcriptId)
    } else {
      await startTranscriptAnalysis(transcriptId)
    }
    showMessage('分析已启动，可关闭页面稍后查看', 'success')
    await loadTranscripts()
  } catch (e) {
    showMessage(e?.response?.data?.detail || '启动分析失败', 'error')
  } finally {
    analyzingIds.value.delete(transcriptId)
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
  const map = { parsed: '待分析', extracting: '提取中', extraction_done: '已提取', comparing: '比对中', comparison_done: '待审核', reviewed: '已审核', error: '失败' }
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
      description: tf === '场景表'
        ? (getVal('解决什么问题') || '') + (getVal('怎样解决') ? ' — ' + getVal('怎样解决') : '')
        : getVal('预期详情') || getVal('detail'),
      title: getVal('场景标题') || getVal('title'),
      status: getVal('预期状态') || getVal('yuqi_status') || '未启动',
      is_first_value: getVal('是否第一价值实现预期') || '否',
      confidence: card.confidence || 0,
      source_quote: card.source_quote || '',
      operationId: card.card_id,
      operationType: card.operation_type || 'create',
      approved: card._manual ? true : (card.operation_type === 'create'),
      rejected: card.operation_type === 'skip',
      _targetForm: tf,
    }
    if (tf === '预期表') expectations.push(item)
    else if (tf === '场景表') scenarios.push(item)
  }
  return { expectations, scenarios }
})

const hasApprovedCards = computed(() => {
  return [...cardGroups.value.expectations, ...cardGroups.value.scenarios].some(c => c.approved)
})

function safeUUID() {
  try { return crypto.randomUUID() } catch { return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random()*16|0; return (c==='x'?r:r&0x3|0x8).toString(16) }) }
}

function loadCardsFromTranscript() {
  const t = selectedTranscript.value
  if (!t) return
  const cards = (t.agent_b_result || {}).result?.operation_cards || []
  selectedCards.value = cards.map(c => ({ ...c, _targetForm: c.target_form }))
  editingItems.value = new Set()
}

async function addManualCard(targetForm) {
  const cardId = safeUUID()
  const newCard = {
    card_id: cardId,
    target_form: targetForm,
    _targetForm: targetForm,
    operation_type: 'create',
    operationType: 'create',
    change_items: [],
    confidence: 0,
    source_quote: '',
    approved: true,
    rejected: false,
    _manual: true,
  }
  try {
    const changeItems = targetForm === '预期表'
      ? [
          { field_name: '预期简述', widget_name: 'detail_brief', new_value: '' },
          { field_name: '预期详情', widget_name: 'detail', new_value: '' },
          { field_name: '预期状态', widget_name: 'yuqi_status', new_value: '未启动' },
          { field_name: '是否第一价值实现预期', widget_name: 'is_first_value', new_value: '否' },
        ]
      : [
          { field_name: '场景标题', widget_name: 'title', new_value: '' },
          { field_name: '解决什么问题', widget_name: 'solve_what_ques', new_value: '' },
          { field_name: '怎样解决', widget_name: 'solve_what_ans', new_value: '' },
        ]
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
}

function switchCardType(type, index, event) {
  const newTarget = event.target.value
  const list = cardGroups.value[type === 'expectation' ? 'expectations' : 'scenarios']
  if (!list || !list[index]) return
  const item = list[index]
  item._targetForm = newTarget
  for (const card of selectedCards.value) {
    if (card.card_id === item.operationId || (card._manual && card.card_id === item.operationId)) {
      card.target_form = newTarget
      card._targetForm = newTarget
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
  if (action === 'approve') { item.approved = true; item.rejected = false }
  else { item.approved = false; item.rejected = true }
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
  const approved = [...cardGroups.value.expectations, ...cardGroups.value.scenarios]
    .filter(c => c.approved)
    .map(c => c.operationId)
  if (!approved.length) return
  submitting.value = true
  try {
    const resp = await executeCards({ transcript_id: selectedId.value, card_ids: approved })
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
