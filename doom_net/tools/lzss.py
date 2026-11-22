"""Small shared LZSS format: flag groups, 2 KB history, 3..34 byte matches."""
from collections import defaultdict,deque
WINDOW=2048
MAX_MATCH=34

def compress(raw):
    raw=bytes(raw);chains=defaultdict(deque);out=bytearray();i=0
    while i<len(raw):
        mark=len(out);out.append(0);flags=0
        for bit in range(8):
            if i>=len(raw):break
            key=raw[i:i+3];chain=chains[key]
            while chain and i-chain[0]>WINDOW:chain.popleft()
            length=0;distance=0
            for j in reversed(chain):
                n=3
                while n<MAX_MATCH and i+n<len(raw) and raw[j+n]==raw[i+n]:n+=1
                if n>length:length=n;distance=i-j
                if n==MAX_MATCH:break
            if length>=3:
                word=((distance-1)<<5)|(length-3)
                out.extend((word&255,word>>8));flags|=1<<bit
            else:length=1;out.append(raw[i])
            for pos in range(i,i+length):
                if pos+3<=len(raw):chains[raw[pos:pos+3]].append(pos)
            i+=length
        out[mark]=flags
    assert decompress(out,len(raw))==raw
    return bytes(out)

def decompress(blob,size):
    out=bytearray();i=0
    while len(out)<size:
        flags=blob[i];i+=1
        for bit in range(8):
            if len(out)>=size:break
            if flags&(1<<bit):
                word=blob[i]|blob[i+1]<<8;i+=2;distance=(word>>5)+1;n=(word&31)+3
                if distance>len(out) or len(out)+n>size:raise ValueError('Invalid backreference')
                for _ in range(n):out.append(out[-distance])
            else:out.append(blob[i]);i+=1
    if i!=len(blob):raise ValueError('Trailing compressed data')
    return bytes(out)
