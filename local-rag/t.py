from app.ingest.chunker import semantic_chunk

if __name__ == '__main__':
    text = "句子1。句子2。句子3。句子4。句子5。句子6。句子7。句子8。句子9。句子10。" * 20
    cs = semantic_chunk(text)
    print(cs)
    # for i, c in enumerate(cs):
    #     print(i,c)