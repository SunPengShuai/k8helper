// 全局变量用于任务控制
let currentTaskId = null;
let isTaskRunning = false;
let cancelRequested = false; // 新增：标记是否已请求取消

let currentFormat = 'auto';

// 全局安全配置变量
let securityConfig = {
    super_admin_mode: false,
    allow_shell_commands: false,
    custom_dangerous_commands: [],
    custom_safe_create_resources: [],
    custom_safe_apply_resources: [],
    custom_safe_scale_resources: [],
    safe_shell_commands: [],
    dangerous_shell_commands: []
};

function setQuery(query) {
    document.getElementById('query-input').value = query;
}

document.getElementById('query-input').addEventListener('keypress', function(e) {
    if (e.key === 'Enter') {
        submitQuery();
    }
});

document.getElementById('submit-btn').addEventListener('click', submitQuery);

async function submitQuery() {
    const query = document.getElementById('query-input').value.trim();
    if (!query) return;
    
    const submitBtn = document.getElementById('submit-btn');
    const resultContainer = document.getElementById('result-container');
    const resultContent = document.getElementById('result-content');
    
    // 重置状态
    cancelRequested = false;
    
    // 生成任务ID
    currentTaskId = Date.now().toString();
    isTaskRunning = true;
    
    // 显示加载状态和中断按钮
    submitBtn.disabled = true;
    submitBtn.innerHTML = '🔄 AI思考中... <button id="cancel-btn" class="cancel-button">⏹️ 中断</button>';
    
    // 立即绑定中断按钮事件（避免延迟）
    const cancelBtn = document.getElementById('cancel-btn');
    if (cancelBtn) {
        cancelBtn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            cancelTask();
        };
    }
    
    resultContainer.style.display = 'block';
    resultContent.innerHTML = '<div class="loading">AI正在分析您的查询并执行相应的kubectl命令</div>';
    
    try {
        const response = await fetch('/api/v1/query', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                query: query,
                task_id: currentTaskId
            })
        });
        
        if (cancelRequested || !isTaskRunning) {
            // 任务已被中断，不处理响应
            return;
        }
        
        const data = await response.json();
        
        if (data.cancelled) {
            resultContent.innerHTML = '<div class="warning">⚠️ 任务已被用户中断</div>';
        } else {
            displayResult(data);
        }
        
    } catch (error) {
        if (isTaskRunning && !cancelRequested) {
            resultContent.innerHTML = `<div class="error">❌ 查询失败: ${error.message}</div>`;
        }
    } finally {
        isTaskRunning = false;
        currentTaskId = null;
        cancelRequested = false;
        submitBtn.disabled = false;
        submitBtn.innerHTML = '🔍 智能查询';
    }
}

// 优化的中断任务函数
async function cancelTask() {
    if (!currentTaskId || !isTaskRunning || cancelRequested) {
        return;
    }
    
    // 立即设置取消标志和UI反馈
    cancelRequested = true;
    
    // 立即更新UI，提供即时反馈
    const cancelBtn = document.getElementById('cancel-btn');
    if (cancelBtn) {
        cancelBtn.innerHTML = '⏳ 中断中...';
        cancelBtn.disabled = true;
        cancelBtn.style.opacity = '0.6';
    }
    
    const resultContent = document.getElementById('result-content');
    resultContent.innerHTML = '<div class="warning">⚠️ 正在中断任务，请稍候...</div>';
    
    try {
        // 异步发送中断请求，不阻塞UI
        const cancelPromise = fetch('/api/v1/cancel', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ task_id: currentTaskId })
        });
        
        // 设置超时，避免中断请求本身卡住
        const timeoutPromise = new Promise((_, reject) => 
            setTimeout(() => reject(new Error('中断请求超时')), 3000)
        );
        
        await Promise.race([cancelPromise, timeoutPromise]);
        
        // 成功中断
        resultContent.innerHTML = '<div class="warning">⚠️ 任务已被用户中断</div>';
        
    } catch (error) {
        console.error('中断任务失败:', error);
        // 即使中断请求失败，也显示中断状态（因为前端已经停止处理）
        resultContent.innerHTML = '<div class="warning">⚠️ 任务已被用户中断</div>';
    } finally {
        // 重置状态
        isTaskRunning = false;
        const submitBtn = document.getElementById('submit-btn');
        submitBtn.disabled = false;
        submitBtn.innerHTML = '🔍 智能查询';
    }
}

function displayResult(data) {
    const aiAnalysis = document.getElementById('ai-analysis');
    const analysisContent = document.getElementById('analysis-content');
    const smartReply = document.getElementById('smart-reply');
    const smartReplyContent = document.getElementById('smart-reply-content');
    const commandInfo = document.getElementById('command-info');
    const commandContent = document.getElementById('command-content');
    const resultContent = document.getElementById('result-content');
    
    // 显示AI分析
    if (data.ai_analysis) {
        aiAnalysis.style.display = 'block';
        analysisContent.textContent = data.ai_analysis;
    } else {
        aiAnalysis.style.display = 'none';
    }
    
    // 显示智能回复
    if (data.smart_reply) {
        smartReply.style.display = 'block';
        smartReplyContent.textContent = data.smart_reply;
    } else {
        smartReply.style.display = 'none';
    }
    
    // 根据执行类型显示不同的命令信息
    if (data.execution_type === 'multi_step' || data.execution_type === 'multi_step_with_retry') {
        // 分步执行显示
        commandInfo.style.display = 'block';
        const steps = data.step_results || [];
        let commandHtml = `<div class="multi-step-info">`;
        commandHtml += `<div class="step-summary">📋 分步执行 (${data.completed_steps}/${data.total_steps})</div>`;
        
        steps.forEach((step, index) => {
            const statusIcon = step.success ? '✅' : '❌';
            const statusClass = step.success ? 'step-success' : 'step-error';
            const retryBadge = (step.retry_count || 0) > 0 ? ` 🔄${step.retry_count}` : '';
            commandHtml += `<div class="step-item ${statusClass}">`;
            commandHtml += `<span class="step-number">${step.step}</span>`;
            commandHtml += `<span class="step-status">${statusIcon}</span>`;
            commandHtml += `<span class="step-command">${escapeHtml(step.command)}${retryBadge}</span>`;
            commandHtml += `</div>`;
        });
        
        commandHtml += `</div>`;
        commandContent.innerHTML = commandHtml;
    } else if (data.command_executed) {
        // 单步执行显示
        commandInfo.style.display = 'block';
        const retryInfo = (data.retry_count || 0) > 0 ? ` (重试${data.retry_count}次)` : '';
        commandContent.innerHTML = `<div class="single-command">${escapeHtml(data.command_executed)}${retryInfo}</div>`;
    } else {
        commandInfo.style.display = 'none';
    }
    
    // 显示结果
    if (!data.success) {
        if (data.execution_type === 'multi_step' || data.execution_type === 'multi_step_with_retry') {
            // 分步执行的错误显示
            displayMultiStepResults(data);
        } else {
            // 单步执行的错误显示
            resultContent.innerHTML = `<div class="error">❌ 执行失败: ${data.execution_result?.error || '未知错误'}</div>`;
        }
        return;
    }
    
    // 根据执行类型显示结果
    if (data.execution_type === 'multi_step' || data.execution_type === 'multi_step_with_retry') {
        displayMultiStepResults(data);
    } else {
        // 单步执行结果显示
        const formatted = data.formatted_result;
        if (!formatted) {
            resultContent.innerHTML = '<div class="error">❌ 没有返回结果</div>';
            return;
        }
        
        resultContent.innerHTML = displaySingleStepResult(formatted, data);
    }
}

function displayMultiStepResults(data) {
    const resultContent = document.getElementById('result-content');
    if (!resultContent) {
        console.error('找不到result-content元素');
        return;
    }
    
    const stepResults = data.step_results || [];
    const totalSteps = data.total_steps || stepResults.length;
    const completedSteps = data.completed_steps || stepResults.length;
    const retryEnabled = data.retry_enabled || false;
    const maxRetries = data.max_retries || 0;
    
    // 计算总重试次数
    const totalRetries = stepResults.reduce((sum, step) => sum + (step.retry_count || 0), 0);
    
    let html = `
        <div class="multi-step-container">
            <div class="multi-step-header">
                <h3>📋 分步执行结果</h3>
                <div class="step-progress">
                    <span class="progress-text">进度: ${completedSteps}/${totalSteps}</span>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${(completedSteps/totalSteps)*100}%"></div>
                    </div>
                </div>
                ${retryEnabled ? `
                    <div class="retry-info">
                        <span class="retry-badge">🔄 智能重试已启用</span>
                        <span class="retry-stats">最大重试: ${maxRetries}次 | 总重试: ${totalRetries}次</span>
                    </div>
                ` : ''}
            </div>
            
            <div class="steps-list">
    `;
    
    stepResults.forEach((step, index) => {
        const stepNumber = step.step || (index + 1);
        const isSuccess = step.success;
        const retryCount = step.retry_count || 0;
        const executionHistory = step.execution_history || [];
        
        // 状态图标和样式
        const statusIcon = isSuccess ? '✅' : '❌';
        const statusClass = isSuccess ? 'success' : 'failed';
        const retryBadge = retryCount > 0 ? `<span class="retry-count-badge">🔄 ${retryCount}次重试</span>` : '';
        
        html += `
            <div class="step-item ${statusClass}">
                <div class="step-header" onclick="toggleStepDetails(${index})">
                    <div class="step-title">
                        <span class="step-icon">${statusIcon}</span>
                        <span class="step-number"> ${stepNumber}</span>
                        <span class="step-command">${escapeHtml(step.command)}</span>
                        ${retryBadge}
                    </div>
                    <span class="toggle-icon" id="toggle-${index}">▼</span>
                </div>
                
                <div class="step-details" id="details-${index}" style="display: none;">
        `;
        
        // 显示执行历史（如果有重试）
        if (executionHistory.length > 1) {
            html += `
                <div class="execution-history">
                    <h4>🔄 执行历史</h4>
            `;
            
            executionHistory.forEach((attempt, attemptIndex) => {
                const attemptSuccess = attempt.result?.success || false;
                const attemptIcon = attemptSuccess ? '✅' : '❌';
                const attemptClass = attemptSuccess ? 'attempt-success' : 'attempt-failed';
                
                html += `
                    <div class="attempt-item ${attemptClass}">
                        <div class="attempt-header">
                            <span class="attempt-icon">${attemptIcon}</span>
                            <span class="attempt-number">尝试 ${attempt.attempt}</span>
                            <span class="attempt-command">${escapeHtml(attempt.command)}</span>
                        </div>
                `;
                
                if (!attemptSuccess && attemptIndex < executionHistory.length - 1) {
                    // 显示失败原因和AI分析
                    html += `
                        <div class="attempt-error">
                            <strong>错误:</strong> ${escapeHtml(attempt.result?.error || '未知错误')}
                        </div>
                    `;
                    
                    // 如果有下一次尝试，显示AI的修复建议
                    const nextAttempt = executionHistory[attemptIndex + 1];
                    if (nextAttempt && nextAttempt.command !== attempt.command) {
                        html += `
                            <div class="ai-suggestion">
                                <span class="ai-icon">🤖</span>
                                <strong>AI修复:</strong> 检测到错误，自动调整为 <code>${escapeHtml(nextAttempt.command)}</code>
                            </div>
                        `;
                    }
                }
                
                html += `</div>`;
            });
            
            html += `</div>`;
        }
        
        // 显示最终结果
        if (isSuccess) {
            const formattedResult = step.formatted_result;
            if (formattedResult) {
                if (formattedResult.type === 'table') {
                    html += displayTableResult(formattedResult);
                } else if (formattedResult.type === 'text') {
                    html += `
                        <div class="step-output">
                            <h4>📄 执行结果</h4>
                            <pre class="command-output">${escapeHtml(formattedResult.content)}</pre>
                        </div>
                    `;
                }
            }
        } else {
            // 显示最终失败信息
            const error = step.execution_result?.error || '未知错误';
            html += `
                <div class="step-error">
                    <h4>❌ 最终错误</h4>
                    <div class="error-message">${escapeHtml(error)}</div>
                    ${retryCount >= maxRetries ? `
                        <div class="retry-exhausted">
                            <span class="warning-icon">⚠️</span>
                            已达到最大重试次数 (${maxRetries})，无法继续重试
                        </div>
                    ` : ''}
                </div>
            `;
        }
        
        html += `
                </div>
            </div>
        `;
    });
    
    html += `
            </div>
            
            <div class="multi-step-summary">
                <div class="summary-stats">
                    <span class="stat-item">
                        <span class="stat-icon">📊</span>
                        总步骤: ${totalSteps}
                    </span>
                    <span class="stat-item ${completedSteps === totalSteps ? 'success' : 'warning'}">
                        <span class="stat-icon">${completedSteps === totalSteps ? '✅' : '⚠️'}</span>
                        完成: ${completedSteps}
                    </span>
                    ${totalRetries > 0 ? `
                        <span class="stat-item retry">
                            <span class="stat-icon">🔄</span>
                            重试: ${totalRetries}次
                        </span>
                    ` : ''}
                </div>
            </div>
        </div>
    `;
    
    resultContent.innerHTML = html;
}

function displayStepResult(formatted, executionResult) {
    if (formatted.type === 'table') {
        let html = '<div class="step-table">';
        html += '<table><thead><tr>';
        formatted.headers.forEach(header => {
            html += `<th>${escapeHtml(header)}</th>`;
        });
        html += '</tr></thead><tbody>';
        
        // 只显示前5行，避免太长
        const displayRows = formatted.data.slice(0, 5);
        displayRows.forEach(row => {
            html += '<tr>';
            row.forEach(cell => {
                html += `<td>${escapeHtml(cell || '')}</td>`;
            });
            html += '</tr>';
        });
        
        if (formatted.data.length > 5) {
            html += `<tr><td colspan="${formatted.headers.length}" class="more-rows">... 还有 ${formatted.data.length - 5} 行</td></tr>`;
        }
        
        html += '</tbody></table>';
        html += `<div class="step-stats">总计: ${formatted.total_rows} 行</div>`;
        html += '</div>';
        return html;
    } else if (formatted.type === 'text') {
        // 文本结果，截取前200字符
        const content = formatted.content || '';
        const truncated = content.length > 200 ? content.substring(0, 200) + '...' : content;
        return `<div class="step-text"><div class="code-block">${escapeHtml(truncated)}</div></div>`;
    } else {
        return `<div class="step-other">${escapeHtml(JSON.stringify(formatted, null, 2))}</div>`;
    }
}

function displaySingleStepResult(formatted, data) {
    let html = '';
    
    if (formatted.type === 'error') {
        html = `<div class="error">❌ ${formatted.error}</div>`;
        if (formatted.content) {
            html += `<div class="code-block">${escapeHtml(formatted.content)}</div>`;
        }
    } else if (formatted.type === 'table') {
        html = '<div class="success">✅ 命令执行成功</div>';
        html += '<div class="format-toggle">';
        html += '<button class="format-btn active" onclick="showTable()">📊 表格视图</button>';
        html += '<button class="format-btn" onclick="showRaw()">📝 原始数据</button>';
        html += '</div>';
        
        html += '<div id="table-view">';
        html += '<table><thead><tr>';
        formatted.headers.forEach(header => {
            html += `<th>${escapeHtml(header)}</th>`;
        });
        html += '</tr></thead><tbody>';
        
        formatted.data.forEach(row => {
            html += '<tr>';
            row.forEach(cell => {
                html += `<td>${escapeHtml(cell || '')}</td>`;
            });
            html += '</tr>';
        });
        html += '</tbody></table>';
        
        html += `<div class="stats">`;
        html += `<div class="stat-item">📊 总行数: ${formatted.total_rows}</div>`;
        html += `<div class="stat-item">📋 列数: ${formatted.headers.length}</div>`;
        html += `</div>`;
        html += '</div>';
        
        // 隐藏的原始数据视图
        html += `<div id="raw-view" style="display: none;">`;
        html += `<div class="code-block">${escapeHtml(data.execution_result?.output || '')}</div>`;
        html += `</div>`;
        
    } else if (formatted.type === 'text') {
        html = '<div class="success">✅ 命令执行成功</div>';
        
        if (formatted.content_type === 'json') {
            try {
                const jsonObj = JSON.parse(formatted.content);
                html += `<div class="code-block">${escapeHtml(JSON.stringify(jsonObj, null, 2))}</div>`;
            } catch (e) {
                html += `<div class="code-block">${escapeHtml(formatted.content)}</div>`;
            }
        } else {
            html += `<div class="code-block">${escapeHtml(formatted.content)}</div>`;
        }
        
        html += `<div class="stats">`;
        html += `<div class="stat-item">📄 行数: ${formatted.line_count}</div>`;
        html += `<div class="stat-item">📝 格式: ${formatted.content_type}</div>`;
        html += `</div>`;
    } else {
        html = `<div class="code-block">${escapeHtml(JSON.stringify(formatted, null, 2))}</div>`;
    }
    
    return html;
}

function showTable() {
    document.getElementById('table-view').style.display = 'block';
    document.getElementById('raw-view').style.display = 'none';
    document.querySelectorAll('.format-btn').forEach(btn => btn.classList.remove('active'));
    event.target.classList.add('active');
}

function showRaw() {
    document.getElementById('table-view').style.display = 'none';
    document.getElementById('raw-view').style.display = 'block';
    document.querySelectorAll('.format-btn').forEach(btn => btn.classList.remove('active'));
    event.target.classList.add('active');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 选项卡切换功能
function switchTab(tabName) {
    // 隐藏所有选项卡内容
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // 移除所有选项卡按钮的激活状态
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // 显示选中的选项卡内容
    document.getElementById(tabName + '-tab').classList.add('active');
    
    // 激活选中的选项卡按钮
    event.target.classList.add('active');
    
    // 如果切换到安全设置选项卡，加载配置
    if (tabName === 'security') {
        loadSecurityConfig();
    }
}

// 加载安全配置
async function loadSecurityConfig() {
    const display = document.getElementById('current-config-display');
    if (display) {
        display.innerHTML = '<div class="loading">🔄 正在加载配置信息...</div>';
    }
    
    try {
        console.log('开始加载安全配置...');
        const response = await fetch('/api/v1/security/config');
        
        if (!response.ok) {
            throw new Error(`HTTP错误: ${response.status} ${response.statusText}`);
        }
        
        const data = await response.json();
        console.log('安全配置API响应:', data);
        
        if (data.success && data.data) {
            securityConfig = data.data.current_config;
            console.log('更新全局配置:', securityConfig);
            updateSecurityUI(data.data);
        } else {
            throw new Error(data.message || '配置加载失败');
        }
    } catch (error) {
        console.error('加载安全配置失败:', error);
        if (display) {
            display.innerHTML = `<div class="error">❌ 加载配置失败: ${error.message}<br><button onclick="loadSecurityConfig()" class="retry-btn">🔄 重试</button></div>`;
        }
    }
}

// 更新安全设置UI
function updateSecurityUI(data) {
    try {
        console.log('开始更新安全设置UI，数据:', data);
        
        const config = data.current_config;
        const defaultConfig = data.default_config;
        
        if (!config) {
            throw new Error('当前配置数据为空');
        }
        
        // 更新超级管理员模式状态
        const toggle = document.getElementById('super-admin-toggle');
        const status = document.getElementById('super-admin-status');
        
        if (toggle && status) {
            toggle.checked = config.super_admin_mode;
            if (config.super_admin_mode) {
                status.textContent = '已启用';
                status.className = 'enabled';
            } else {
                status.textContent = '已禁用';
                status.className = 'disabled';
            }
            console.log('超级管理员状态更新完成:', config.super_admin_mode);
        }
        
        // 更新shell命令状态
        const shellToggle = document.getElementById('shell-commands-toggle');
        const shellStatus = document.getElementById('shell-commands-status');
        
        if (shellToggle && shellStatus) {
            shellToggle.checked = config.allow_shell_commands;
            if (config.allow_shell_commands) {
                shellStatus.textContent = '已启用';
                shellStatus.className = 'enabled';
            } else {
                shellStatus.textContent = '已禁用';
                shellStatus.className = 'disabled';
            }
            console.log('Shell命令状态更新完成:', config.allow_shell_commands);
        }
        
        // 更新标签显示（添加错误处理）
        try {
            updateTags('dangerous-commands-tags', config.custom_dangerous_commands, defaultConfig.default_dangerous_commands);
            console.log('危险命令标签更新完成');
        } catch (e) {
            console.warn('更新危险命令标签失败:', e);
        }
        
        try {
            updateTags('safe-create-tags', config.custom_safe_create_resources, defaultConfig.default_safe_create_resources);
            console.log('安全创建资源标签更新完成');
        } catch (e) {
            console.warn('更新安全创建资源标签失败:', e);
        }
        
        try {
            updateTags('safe-apply-tags', config.custom_safe_apply_resources, defaultConfig.default_safe_apply_resources);
            console.log('安全应用资源标签更新完成');
        } catch (e) {
            console.warn('更新安全应用资源标签失败:', e);
        }
        
        try {
            updateTags('safe-scale-tags', config.custom_safe_scale_resources, defaultConfig.default_safe_scale_resources);
            console.log('安全扩缩容资源标签更新完成');
        } catch (e) {
            console.warn('更新安全扩缩容资源标签失败:', e);
        }
        
        // 更新配置显示
        try {
            updateConfigDisplay(config, defaultConfig);
            console.log('配置显示更新完成');
        } catch (e) {
            console.warn('更新配置显示失败:', e);
        }
        
        // 更新shell状态
        try {
            loadShellStatus();
            console.log('Shell状态加载完成');
        } catch (e) {
            console.warn('加载shell状态失败:', e);
        }
        
        console.log('安全设置UI更新完成');
        
    } catch (error) {
        console.error('更新安全设置UI失败:', error);
        console.error('错误数据:', data);
        // 显示错误信息给用户
        const configDisplay = document.getElementById('current-config-display');
        if (configDisplay) {
            configDisplay.innerHTML = `<div class="error">❌ 更新配置显示失败: ${error.message}<br><button onclick="loadSecurityConfig()" class="retry-btn">🔄 重试</button></div>`;
        }
    }
}

// 更新标签显示
function updateTags(containerId, customItems, defaultItems) {
    const container = document.getElementById(containerId);
    if (!container) {
        console.warn(`标签容器 ${containerId} 不存在`);
        return;
    }
    
    // 确保参数是数组
    const safeCustomItems = Array.isArray(customItems) ? customItems : [];
    const safeDefaultItems = Array.isArray(defaultItems) ? defaultItems : [];
    
    container.innerHTML = '';
    
    // 显示默认项目（不可删除）
    safeDefaultItems.forEach(item => {
        try {
            const tag = createTag(item, true);
            container.appendChild(tag);
        } catch (e) {
            console.warn(`创建默认标签失败: ${item}`, e);
        }
    });
    
    // 显示自定义项目（可删除）
    safeCustomItems.forEach(item => {
        try {
            const tag = createTag(item, false);
            container.appendChild(tag);
        } catch (e) {
            console.warn(`创建自定义标签失败: ${item}`, e);
        }
    });
}

// 创建标签元素
function createTag(text, isDefault) {
    const tag = document.createElement('div');
    tag.className = isDefault ? 'tag default' : 'tag';
    tag.innerHTML = `
        <span>${escapeHtml(text)}</span>
        ${!isDefault ? '<button class="tag-remove" onclick="removeTag(this)">×</button>' : ''}
    `;
    tag.dataset.value = text;
    return tag;
}

// 删除标签
function removeTag(button) {
    const tag = button.parentElement;
    const container = tag.parentElement;
    const value = tag.dataset.value;
    
    // 从对应的配置数组中移除
    const containerId = container.id;
    if (containerId === 'dangerous-commands-tags') {
        securityConfig.custom_dangerous_commands = securityConfig.custom_dangerous_commands.filter(item => item !== value);
    } else if (containerId === 'safe-create-tags') {
        securityConfig.custom_safe_create_resources = securityConfig.custom_safe_create_resources.filter(item => item !== value);
    } else if (containerId === 'safe-apply-tags') {
        securityConfig.custom_safe_apply_resources = securityConfig.custom_safe_apply_resources.filter(item => item !== value);
    } else if (containerId === 'safe-scale-tags') {
        securityConfig.custom_safe_scale_resources = securityConfig.custom_safe_scale_resources.filter(item => item !== value);
    }
    
    tag.remove();
}

// 添加标签输入事件监听
function setupTagInputs() {
    const inputs = [
        { id: 'dangerous-commands-input', config: 'custom_dangerous_commands', container: 'dangerous-commands-tags' },
        { id: 'safe-create-input', config: 'custom_safe_create_resources', container: 'safe-create-tags' },
        { id: 'safe-apply-input', config: 'custom_safe_apply_resources', container: 'safe-apply-tags' },
        { id: 'safe-scale-input', config: 'custom_safe_scale_resources', container: 'safe-scale-tags' }
    ];
    
    inputs.forEach(({ id, config, container }) => {
        const input = document.getElementById(id);
        if (input) {
            input.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    const value = this.value.trim();
                    if (value && securityConfig[config] && !securityConfig[config].includes(value)) {
                        securityConfig[config].push(value);
                        const containerEl = document.getElementById(container);
                        if (containerEl) {
                            const tag = createTag(value, false);
                            containerEl.appendChild(tag);
                        }
                        this.value = '';
                    }
                }
            });
        } else {
            console.warn(`标签输入框 ${id} 不存在`);
        }
    });
}

// 超级管理员模式切换
async function toggleSuperAdmin() {
    const toggle = document.getElementById('super-admin-toggle');
    const status = document.getElementById('super-admin-status');
    
    try {
        const endpoint = toggle.checked ? '/api/v1/security/super-admin/enable' : '/api/v1/security/super-admin/disable';
        const response = await fetch(endpoint, { method: 'POST' });
        const data = await response.json();
        
        console.log('超级管理员切换API响应:', data);
        
        if (data.success && data.current_config) {
            // 更新全局配置
            securityConfig.super_admin_mode = data.current_config.super_admin_mode;
            securityConfig.allow_shell_commands = data.current_config.allow_shell_commands;
            
            // 更新UI显示
            if (data.current_config.super_admin_mode) {
                status.textContent = '已启用';
                status.className = 'enabled';
            } else {
                status.textContent = '已禁用';
                status.className = 'disabled';
            }
            
            // 更新配置显示区域
            try {
                loadSecurityConfig();
            } catch (e) {
                console.warn('重新加载配置失败:', e);
            }
            
            console.log('超级管理员状态更新完成:', data.current_config.super_admin_mode);
        } else {
            // 恢复开关状态
            toggle.checked = !toggle.checked;
            alert('切换失败: ' + (data.message || '未知错误'));
        }
    } catch (error) {
        console.error('超级管理员切换失败:', error);
        // 恢复开关状态
        toggle.checked = !toggle.checked;
        alert('切换失败: ' + error.message);
    }
}

// 保存安全配置
async function saveSecurityConfig() {
    const saveBtn = document.getElementById('save-config-btn');
    const originalText = saveBtn.textContent;
    
    try {
        saveBtn.textContent = '💾 保存中...';
        saveBtn.disabled = true;
        
        const response = await fetch('/api/v1/security/config', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                dangerous_commands: securityConfig.custom_dangerous_commands,
                safe_create_resources: securityConfig.custom_safe_create_resources,
                safe_apply_resources: securityConfig.custom_safe_apply_resources,
                safe_scale_resources: securityConfig.custom_safe_scale_resources
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            alert('✅ 安全配置保存成功！');
            securityConfig = data.current_config;
        } else {
            alert('❌ 保存失败: ' + (data.message || '未知错误'));
        }
    } catch (error) {
        alert('❌ 保存失败: ' + error.message);
    } finally {
        saveBtn.textContent = originalText;
        saveBtn.disabled = false;
    }
}

// 重置安全配置
async function resetSecurityConfig() {
    if (!confirm('确定要重置所有安全配置到默认状态吗？这将清除所有自定义设置。')) {
        return;
    }
    
    const resetBtn = document.getElementById('reset-config-btn');
    const originalText = resetBtn.textContent;
    
    try {
        resetBtn.textContent = '🔄 重置中...';
        resetBtn.disabled = true;
        
        const response = await fetch('/api/v1/security/reset', { method: 'POST' });
        const data = await response.json();
        
        if (data.success) {
            alert('✅ 安全配置已重置为默认状态！');
            securityConfig = data.current_config;
            loadSecurityConfig(); // 重新加载UI
        } else {
            alert('❌ 重置失败: ' + (data.message || '未知错误'));
        }
    } catch (error) {
        alert('❌ 重置失败: ' + error.message);
    } finally {
        resetBtn.textContent = originalText;
        resetBtn.disabled = false;
    }
}

// 更新配置显示
function updateConfigDisplay(config, defaultConfig) {
    const display = document.getElementById('current-config-display');
    if (!display) {
        console.warn('配置显示容器不存在');
        return;
    }
    
    try {
        // 确保配置对象存在
        const safeConfig = config || {};
        const safeDefaultConfig = defaultConfig || {};
        
        // 安全的数组处理函数
        function safeArrayToTags(arr, className = 'config-tag') {
            if (!Array.isArray(arr)) return '';
            return arr.map(item => {
                try {
                    return `<span class="${className}">${escapeHtml(String(item || ''))}</span>`;
                } catch (e) {
                    console.warn('创建标签失败:', item, e);
                    return '';
                }
            }).filter(tag => tag).join('');
        }
        
        const html = `
            <div class="config-item">
                <h5>🔧 超级管理员模式</h5>
                <div class="config-list">
                    <span class="config-tag ${safeConfig.super_admin_mode ? 'active' : ''}">${safeConfig.super_admin_mode ? '已启用' : '已禁用'}</span>
                </div>
            </div>
            
            <div class="config-item">
                <h5>💻 Shell命令支持</h5>
                <div class="config-list">
                    <span class="config-tag ${safeConfig.allow_shell_commands ? 'active' : ''}">${safeConfig.allow_shell_commands ? '已启用' : '已禁用'}</span>
                </div>
            </div>
            
            <div class="config-item">
                <h5>🚫 危险命令 (默认 + 自定义)</h5>
                <div class="config-list">
                    ${safeArrayToTags(safeDefaultConfig.default_dangerous_commands)}
                    ${safeArrayToTags(safeConfig.custom_dangerous_commands, 'config-tag active')}
                </div>
            </div>
            
            <div class="config-item">
                <h5>✅ 允许创建的资源 (默认 + 自定义)</h5>
                <div class="config-list">
                    ${safeArrayToTags(safeDefaultConfig.default_safe_create_resources)}
                    ${safeArrayToTags(safeConfig.custom_safe_create_resources, 'config-tag active')}
                </div>
            </div>
            
            <div class="config-item">
                <h5>📝 允许Apply的资源 (默认 + 自定义)</h5>
                <div class="config-list">
                    ${safeArrayToTags(safeDefaultConfig.default_safe_apply_resources)}
                    ${safeArrayToTags(safeConfig.custom_safe_apply_resources, 'config-tag active')}
                </div>
            </div>
            
            <div class="config-item">
                <h5>📏 允许扩缩容的资源 (默认 + 自定义)</h5>
                <div class="config-list">
                    ${safeArrayToTags(safeDefaultConfig.default_safe_scale_resources)}
                    ${safeArrayToTags(safeConfig.custom_safe_scale_resources, 'config-tag active')}
                </div>
            </div>
        `;
        
        display.innerHTML = html;
        console.log('配置显示更新成功');
    } catch (error) {
        console.error('更新配置显示失败:', error);
        console.error('配置数据:', { config, defaultConfig });
        display.innerHTML = '<div class="error">❌ 配置显示更新失败，请刷新页面重试</div>';
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    try {
        // 设置标签输入
        setupTagInputs();
        
        // 超级管理员开关事件
        const superAdminToggle = document.getElementById('super-admin-toggle');
        if (superAdminToggle) {
            superAdminToggle.addEventListener('change', toggleSuperAdmin);
        }
        
        // Shell命令开关事件
        const shellCommandsToggle = document.getElementById('shell-commands-toggle');
        if (shellCommandsToggle) {
            shellCommandsToggle.addEventListener('change', toggleShellCommands);
        }
        
        // 保存配置按钮事件
        const saveConfigBtn = document.getElementById('save-config-btn');
        if (saveConfigBtn) {
            saveConfigBtn.addEventListener('click', saveSecurityConfig);
        }
        
        // 重置配置按钮事件
        const resetConfigBtn = document.getElementById('reset-config-btn');
        if (resetConfigBtn) {
            resetConfigBtn.addEventListener('click', resetSecurityConfig);
        }
        
        // 刷新配置按钮事件
        const refreshConfigBtn = document.getElementById('refresh-config-btn');
        if (refreshConfigBtn) {
            refreshConfigBtn.addEventListener('click', loadSecurityConfig);
        }
        
        // Shell命令相关按钮事件
        const validateShellBtn = document.getElementById('validate-shell-btn');
        if (validateShellBtn) {
            validateShellBtn.addEventListener('click', validateShellCommand);
        }
        
        const executeShellBtn = document.getElementById('execute-shell-btn');
        if (executeShellBtn) {
            executeShellBtn.addEventListener('click', executeShellCommand);
        }
        
        // Shell命令输入框快捷键
        const shellCommandInput = document.getElementById('shell-command-input');
        if (shellCommandInput) {
            shellCommandInput.addEventListener('keydown', function(e) {
                if (e.ctrlKey && e.key === 'Enter') {
                    e.preventDefault();
                    executeShellCommand();
                } else if (e.ctrlKey && e.key === 'r') {
                    e.preventDefault();
                    validateShellCommand();
                }
            });
        }
        
        console.log('页面初始化完成');
    } catch (error) {
        console.error('页面初始化失败:', error);
    }
});

// 切换步骤详情显示
function toggleStepDetails(stepIndex) {
    const detailsElement = document.getElementById(`details-${stepIndex}`);
    const toggleIcon = document.getElementById(`toggle-${stepIndex}`);
    
    if (detailsElement.style.display === 'none') {
        detailsElement.style.display = 'block';
        toggleIcon.textContent = '▲';
    } else {
        detailsElement.style.display = 'none';
        toggleIcon.textContent = '▼';
    }
}

// 将函数添加到全局作用域，以便HTML onclick可以调用
window.toggleStepDetails = toggleStepDetails;

// 添加displayTableResult函数（如果不存在）
function displayTableResult(formattedResult) {
    let html = '<div class="step-table">';
    html += '<table><thead><tr>';
    formattedResult.headers.forEach(header => {
        html += `<th>${escapeHtml(header)}</th>`;
    });
    html += '</tr></thead><tbody>';
    
    // 只显示前5行，避免太长
    const displayRows = formattedResult.data.slice(0, 5);
    displayRows.forEach(row => {
        html += '<tr>';
        row.forEach(cell => {
            html += `<td>${escapeHtml(cell || '')}</td>`;
        });
        html += '</tr>';
    });
    
    if (formattedResult.data.length > 5) {
        html += `<tr><td colspan="${formattedResult.headers.length}" class="more-rows">... 还有 ${formattedResult.data.length - 5} 行数据</td></tr>`;
    }
    
    html += '</tbody></table></div>';
    return html;
}

// Shell命令相关功能
function setShellCommand(command) {
    document.getElementById('shell-command-input').value = command;
}

async function loadShellStatus() {
    try {
        const response = await fetch('/api/v1/shell/status');
        const data = await response.json();
        
        if (data.success) {
            updateShellStatusUI(data.data);
        } else {
            console.error('加载shell状态失败');
        }
    } catch (error) {
        console.error('加载shell状态失败:', error);
        updateShellStatusUI({
            shell_commands_enabled: false,
            super_admin_mode: false
        });
    }
}

function updateShellStatusUI(status) {
    const statusDot = document.getElementById('shell-status-dot');
    const statusText = document.getElementById('shell-status-text');
    
    if (status.shell_commands_enabled || status.super_admin_mode) {
        statusDot.className = 'status-dot enabled';
        statusText.textContent = status.super_admin_mode ? 'Shell命令已启用 (超级管理员模式)' : 'Shell命令已启用';
    } else {
        statusDot.className = 'status-dot disabled';
        statusText.textContent = 'Shell命令已禁用';
    }
}

async function validateShellCommand() {
    const command = document.getElementById('shell-command-input').value.trim();
    const validateBtn = document.getElementById('validate-shell-btn');
    const validationResult = document.getElementById('shell-validation-result');
    const validationContent = document.getElementById('validation-content');
    
    if (!command) {
        alert('请输入要验证的命令');
        return;
    }
    
    const originalText = validateBtn.textContent;
    validateBtn.textContent = '🔍 验证中...';
    validateBtn.disabled = true;
    
    try {
        const response = await fetch('/api/v1/shell/validate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(command)
        });
        
        const data = await response.json();
        
        if (data.success && data.data) {
            displayValidationResult(data.data);
            validationResult.style.display = 'block';
        } else {
            validationContent.innerHTML = `<div class="error">验证失败: ${data.data?.error || '未知错误'}</div>`;
            validationResult.style.display = 'block';
        }
        
    } catch (error) {
        validationContent.innerHTML = `<div class="error">验证失败: ${error.message}</div>`;
        validationResult.style.display = 'block';
    } finally {
        validateBtn.textContent = originalText;
        validateBtn.disabled = false;
    }
}

function displayValidationResult(data) {
    const validationContent = document.getElementById('validation-content');
    
    const safetyClass = data.is_safe ? 'safe' : 'unsafe';
    const safetyIcon = data.is_safe ? '✅' : '❌';
    const canExecuteIcon = data.can_execute ? '▶️' : '🚫';
    
    let html = `
        <div class="validation-summary ${safetyClass}">
            <div class="validation-item">
                <span class="validation-label">命令安全性:</span>
                <span class="validation-value">${safetyIcon} ${data.safety_message}</span>
            </div>
            <div class="validation-item">
                <span class="validation-label">可执行性:</span>
                <span class="validation-value">${canExecuteIcon} ${data.can_execute ? '可以执行' : '无法执行'}</span>
            </div>
            <div class="validation-item">
                <span class="validation-label">命令类型:</span>
                <span class="validation-value">${data.syntax_analysis.command_type}</span>
            </div>
            <div class="validation-item">
                <span class="validation-label">复杂度:</span>
                <span class="validation-value">${data.syntax_analysis.complexity === 'simple' ? '简单' : '复杂'}</span>
            </div>
        </div>
    `;
    
    if (data.syntax_analysis.features_used && data.syntax_analysis.features_used.length > 0) {
        html += `
            <div class="validation-features">
                <h4>使用的功能:</h4>
                <div class="feature-tags">
                    ${data.syntax_analysis.features_used.map(feature => `<span class="feature-tag">${feature}</span>`).join('')}
                </div>
            </div>
        `;
    }
    
    if (data.recommendations && data.recommendations.length > 0) {
        html += `
            <div class="validation-recommendations">
                <h4>建议:</h4>
                <ul>
                    ${data.recommendations.filter(rec => rec).map(rec => `<li>${rec}</li>`).join('')}
                </ul>
            </div>
        `;
    }
    
    validationContent.innerHTML = html;
}

async function executeShellCommand() {
    const command = document.getElementById('shell-command-input').value.trim();
    const timeout = parseInt(document.getElementById('shell-timeout').value);
    const executeBtn = document.getElementById('execute-shell-btn');
    const executionResult = document.getElementById('shell-execution-result');
    const executionContent = document.getElementById('execution-content');
    const executionCommand = document.getElementById('execution-command');
    const executionStatus = document.getElementById('execution-status');
    
    if (!command) {
        alert('请输入要执行的命令');
        return;
    }
    
    const originalText = executeBtn.textContent;
    executeBtn.textContent = '⏳ 执行中...';
    executeBtn.disabled = true;
    
    executionResult.style.display = 'block';
    executionCommand.textContent = command;
    executionStatus.textContent = '执行中...';
    executionContent.innerHTML = '<div class="loading">正在执行命令，请稍候...</div>';
    
    try {
        const response = await fetch('/api/v1/shell/execute', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                command: command,
                timeout: timeout
            })
        });
        
        const data = await response.json();
        displayExecutionResult(data);
        
    } catch (error) {
        executionStatus.textContent = '执行失败';
        executionContent.innerHTML = `<div class="error">执行失败: ${error.message}</div>`;
    } finally {
        executeBtn.textContent = originalText;
        executeBtn.disabled = false;
    }
}

function displayExecutionResult(data) {
    const executionStatus = document.getElementById('execution-status');
    const executionContent = document.getElementById('execution-content');
    
    const statusIcon = data.success ? '✅' : '❌';
    const statusText = data.success ? '执行成功' : '执行失败';
    const statusClass = data.success ? 'success' : 'error';
    
    executionStatus.innerHTML = `<span class="${statusClass}">${statusIcon} ${statusText}</span>`;
    
    let html = `
        <div class="execution-info">
            <div class="info-item">
                <span class="info-label">命令:</span>
                <span class="info-value">${escapeHtml(data.command)}</span>
            </div>
            <div class="info-item">
                <span class="info-label">命令类型:</span>
                <span class="info-value">${data.command_type}</span>
            </div>
            <div class="info-item">
                <span class="info-label">返回码:</span>
                <span class="info-value">${data.return_code}</span>
            </div>
            <div class="info-item">
                <span class="info-label">执行时间:</span>
                <span class="info-value">${data.execution_time}秒超时</span>
            </div>
        </div>
    `;
    
    if (data.success && data.output) {
        html += `
            <div class="execution-output">
                <h4>输出结果:</h4>
                <div class="output-content">
                    ${displayFormattedOutput(data.formatted_result)}
                </div>
            </div>
        `;
    }
    
    if (data.error) {
        html += `
            <div class="execution-error">
                <h4>错误信息:</h4>
                <div class="error-content">
                    <pre>${escapeHtml(data.error)}</pre>
                </div>
            </div>
        `;
    }
    
    executionContent.innerHTML = html;
}

function displayFormattedOutput(formatted) {
    if (!formatted) return '<div class="no-output">无输出内容</div>';
    
    switch (formatted.type) {
        case 'table':
            return displayTableResult(formatted);
        case 'error':
            return `<div class="error"><pre>${escapeHtml(formatted.error)}</pre></div>`;
        case 'text':
        default:
            return `<div class="text-output"><pre>${escapeHtml(formatted.content || formatted.output || '')}</pre></div>`;
    }
}

async function toggleShellCommands() {
    const toggle = document.getElementById('shell-commands-toggle');
    const status = document.getElementById('shell-commands-status');
    
    try {
        const endpoint = toggle.checked ? '/api/v1/security/shell-commands/enable' : '/api/v1/security/shell-commands/disable';
        const response = await fetch(endpoint, { method: 'POST' });
        const data = await response.json();
        
        if (data.success) {
            securityConfig.allow_shell_commands = data.current_config.allow_shell_commands;
            if (data.current_config.allow_shell_commands) {
                status.textContent = '已启用';
                status.className = 'enabled';
            } else {
                status.textContent = '已禁用';
                status.className = 'disabled';
            }
            
            // 更新shell状态
            loadShellStatus();
        } else {
            // 恢复开关状态
            toggle.checked = !toggle.checked;
            alert('切换失败: ' + (data.message || '未知错误'));
        }
    } catch (error) {
        // 恢复开关状态
        toggle.checked = !toggle.checked;
        alert('切换失败: ' + error.message);
    }
} 