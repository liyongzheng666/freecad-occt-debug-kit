"""确定性工具层（agent-native typed I/O，G2）。

知识下沉到这里：能算的、能查的全放工具，prompt 只负责选路。
每个工具结果都应落 session（同时进 viewer + 进轨迹）。
"""
