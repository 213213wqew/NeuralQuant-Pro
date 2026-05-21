import os
import openai
from quant_app.core.logger import get_logger

logger = get_logger("AIResearchAnalyst")

class AIResearchAnalyst:
    """
    独立行情分析大脑：完全独立于交易策略。
    功能：接收量化指标 + 宏观新闻 + AI 风险评分 -> 产出深度行情报告。
    """
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or os.getenv("RESEARCH_AI_KEY")
        self.base_url = base_url or "https://api.openai.com/v1"
        
        if self.api_key:
            self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
        else:
            self.client = None
            logger.warning("AIResearch: 未配置 API Key，将进入‘离线模拟判断’模式")

    def get_market_analysis(self, 
                           symbol, 
                           risk_score=None, 
                           dir_score=None, 
                           technical_summary=None,
                           macro_context=None):
        """
        核心函数：生成全方位的行情研判结论。
        
        参数:
        - symbol: 交易品种 (如 XAUUSD)
        - risk_score: 来自 modules.ai 的风险分 (0-100)
        - dir_score: 来自 modules.ai 的方向信心 (0-100)
        - technical_summary: 当前的指标快照 (MA, RSI, 布林带等)
        - macro_context: 外部输入的新闻或宏观背景
        """
        
        # 1. 整理数据上下文
        context = f"""
        【分析对象】: {symbol}
        【量化风控分】: {risk_score if risk_score is not None else '未提供'} (分值越高代表补仓风险越大)
        【方向信心分】: {dir_score if dir_score is not None else '未提供'} (越接近100越看涨，越接近0越看跌)
        【技术指标汇总】: {technical_summary or '暂无数据'}
        【宏观背景/新闻】: {macro_context or '暂无突发新闻'}
        """

        if not self.client:
            return f"--- 离线模拟报告 ---\n{context}\n结论：请配置 API Key 以获取 AI 深度分析。"

        # 2. 构建 AI 提示词 (Prompt)
        prompt = f"""
        你是一位顶级的量化策略分析师。请基于以下提供的【数据上下文】，进行深度研判。
        
        {context}
        
        请给出：
        1. **形式研判**：目前的走势是处于“蓄势”、“出货”还是“单边陷阱”？
        2. **多空建议**：结合信心分，目前是应该持仓观望、果断入场还是准备撤退？
        3. **风险警告**：如果风控分较高，请结合技术指标解释具体危险在哪里。
        
        注意：请使用专业、简洁、有说服力的金融口吻回复。
        """

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o", # 默认使用最强的模型
                messages=[
                    {"role": "system", "content": "你是一个理性的 AI 量化分析专家。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4 # 降低随机性，保证分析的严谨
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"AI 分析失败: {e}")
            return f"分析过程中发生错误: {str(e)}"

    def analyze_patterns(self, price_history):
        """
        将来可以接入：分析特定的 K 线形态（如 W 底，三角形等）
        """
        pass
