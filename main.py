# local supply agent：线索提取demo
import requests
import time

def get_public_clue_sample():
    headers = {"User-Agent":"Mozilla/5.0 (Windows NT10; Win64; x64) AppleWebKit/537.36"}
    try:
        # 示例：模拟拉取公开页面文本（仅学习用途）
        time.sleep(1.2) # 防限流延迟
        return {"status":"ok","keywords":["获客","推广","需求"]}
    except Exception as e:
        return {"status":"fail","error":str(e)}

if __name__ == "__main__":
    res = get_public_clue_sample()
    print("提取关键词：", res)
