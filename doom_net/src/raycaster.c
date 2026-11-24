/* UniDoom Direct: ARM rendering and presentation into UniCard's VGA buffer.
 * 160 DDA rays, textured floor/ceiling, lifting doors and occluded billboards.
 * The 160x160 view is written directly as doubled horizontal Sharp pixels.
 */
#include <stdint.h>
#include "font.h"
#include "sine.h"
#include "assets.h"
#define TOP 8
#define BOTTOM 167
#define HORIZON 88
#define RAYS 160
#define FORWARD 1
#define BACKWARD 2
#define TURN_LEFT 4
#define TURN_RIGHT 8
#define STRAFE_LEFT 16
#define STRAFE_RIGHT 32
#define FIRE 64
#define USE 128

typedef struct {uint8_t key,initialized,buttons,sound;} ABI;
#ifdef UNIDOOM_NATIVE
ABI abi;
uint32_t video_address;
static uint32_t firmware_video_pointer=0x10001f80;
_Alignas(4) static uint8_t framebuffer[32768],video[32768];
#define FB framebuffer
#else
extern volatile ABI abi;
extern volatile uint32_t video_address;
extern const volatile uint32_t firmware_video_pointer;
extern uint8_t __back_buffer[];
#define FB __back_buffer
#endif
static uint8_t art[ART_BYTES],world_map[MAP_H][MAP_W];
#define textures ((uint8_t (*)[512])art)
#define sprites ((uint8_t (*)[512])(art+4096))
typedef struct {float x,y;int hp,flash,dir;} Drone;
typedef struct {uint32_t step;uint16_t height;uint8_t u,meta;} WallColumn;
typedef struct {float x,y,z;int8_t vx,vy,vz,life;uint8_t color;} Particle;
typedef struct {float depth;int u,side,tile,door;} Hit;
typedef struct {
    uint8_t mode,slot,mask,ui;
    uint16_t tick,hash;
    char code[4];
    uint8_t error,ready,input[4][2],sector,slots;
} Network;
#ifdef UNIDOOM_NATIVE
Network network;
#else
extern volatile Network network;
#endif
#define PLAYER_FIELDS(X) X(angle) X(health) X(ammo) X(fire_timer) X(cooldown) X(hurt_timer) X(walk_phase) X(weapon) X(running) X(use_down)
typedef struct {float x,y;
#define FIELD(n) int16_t n;
    PLAYER_FIELDS(FIELD)
#undef FIELD
    int16_t score,respawn,shield;
} NetPlayer;
static NetPlayer peers[4];
static int mp_active,active_peer;
static uint16_t processed_tick;
static void net_hit(float dx,float dy);
static void net_hud(void);
static float player_x,player_y;
static int angle,health,ammo,kills,core,medkit,won,frame,fire_timer,cooldown,hurt_timer;
static int map_on,flashlight,running,auto_mode,tour_index,use_down,walk_phase,message;
static int door_open[2],door_goal[2];
static Drone drones[DRONE_COUNT];
static int god_mode,cheat_pos,cheat_message,ai_on;
static int sector,blue_key,secret_found,notice,tour_x,tour_y,nav_seed,weapon;
static uint8_t nav_dist[MAP_W*MAP_H];
static union {uint16_t queue[MAP_W*MAP_H];struct {WallColumn columns[RAYS];uint16_t keys[32];uint8_t colors[32][16];} rays;} scratch;
#define nav_queue scratch.queue
#define columns scratch.rays.columns
#define column_colors scratch.rays.colors
static uint8_t column_index[RAYS];
static uint8_t door_uv[2][RAYS];
static Particle particles[16];
static unsigned particle_head;
static float wall_depth[RAYS],door_depth[2][RAYS];
static int16_t door_bottom[2][RAYS];
static const uint8_t door_pos[2][2]={{6,3},{6,13}};
static const int8_t dirx[]={1,0,-1,0},diry[]={0,1,0,-1};
static void unpack(uint8_t *dest,const uint8_t *source,unsigned size) {
    unsigned i=0;
    while(i<size){unsigned flags=*source++;
        for(int bit=0;bit<8 && i<size;++bit,flags>>=1){
            if(flags&1){unsigned word=*source++;word|=(unsigned)*source++<<8;
                unsigned distance=(word>>5)+1,n=(word&31)+3;
                while(n--){dest[i]=dest[i-distance];++i;}
            }else dest[i++]=*source++;
        }
    }
}
static void notify(int kind){notice=kind;message=36;}
static unsigned texel(const uint8_t *data,unsigned index) {
    return (data[index>>1]>>((index&1)*4))&15;
}

static float sine(int a) {
    unsigned q=((unsigned)a&1023)>>8,i=(unsigned)a&255;
    int n=sine_quarter[(q&1)?256-i:i];
    return (q&2?-n:n)*(1.0f/32767.0f);
}
static float absf(float x) {return x<0?-x:x;}
static int mini(int a,int b) {return a<b?a:b;}
static int maxi(int a,int b) {return a>b?a:b;}
static void pixel(int x,int y,unsigned color) {
    if ((unsigned)x>=320 || (unsigned)y>=200)return;
    unsigned off=y*40+(x>>3),mask=1u<<(x&7);
    for(unsigned p=0;p<4;++p) {
        volatile uint8_t *dest=FB+p*8192+off;
        *dest=(*dest&~mask)|((color&(1u<<p))?mask:0);
    }
}
static void pixel2(int x,int y,unsigned color) {
    unsigned off=y*40+(x>>2),mask=3u<<((x&3)*2);
    for(unsigned p=0;p<4;++p) {
        volatile uint8_t *dest=FB+p*8192+off;
        *dest=(*dest&~mask)|((color&(1u<<p))?mask:0);
    }
}
static void rect(int x,int y,int w,int h,int color) {
    for(int yy=maxi(y,0);yy<mini(y+h,200);++yy)
        for(int xx=maxi(x,0);xx<mini(x+w,320);++xx)pixel(xx,yy,color);
}
static int text(int x,int y,const char *s,int color) {
    for(;*s && x<315;++s,x+=6) {
        unsigned c=(unsigned char)*s;
        if(c<32 || c>90)continue;
        for(int dx=0;dx<5;++dx)for(int dy=0;dy<7;++dy)
            if(font[c-32][dx]&(1<<dy))pixel(x+dx,y+dy,color);
    }
    return x;
}
static int number(int x,int y,unsigned value,int digits,int color) {
    char out[8];out[digits]=0;
    for(int i=digits-1;i>=0;--i){out[i]='0'+value%10;value/=10;}
    return text(x,y,out,color);
}
static int tile(int x,int y) {
    if((unsigned)x>=MAP_W || (unsigned)y>=MAP_H)return 1;
    return world_map[y][x];
}
static int door_index(int x,int y) {
    for(int i=0;i<2;++i)if(door_pos[i][0]==x && door_pos[i][1]==y)return i;
    return -1;
}
static int solid(int x,int y) {
    int t=tile(x,y);
    if(t==5){int i=door_index(x,y);return i<0 || door_open[i]<14;}
    return t!=0;
}
static int can_stand(float x,float y) {
    const float r=.21f;
    for(int yy=(int)(y-r);yy<=(int)(y+r);++yy)
        for(int xx=(int)(x-r);xx<=(int)(x+r);++xx) {
            if(!solid(xx,yy))continue;
            float nx=x<xx?xx:x>xx+1?xx+1:x;
            float ny=y<yy?yy:y>yy+1?yy+1:y;
            float dx=x-nx,dy=y-ny;
            if(dx*dx+dy*dy<r*r)return 0;
        }
    return x>.21f && y>.21f && x<MAP_W-.21f && y<MAP_H-.21f;
}
static void move(float dx,float dy) {
    if(can_stand(player_x+dx,player_y))player_x+=dx;
    if(can_stand(player_x,player_y+dy))player_y+=dy;
}

/* Collect the partial doors before the nearest opaque wall. Non-rendering
 * visibility tests pass eye=1: a door more than half raised clears eye level.
 */
static Hit trace(float rx,float ry,Hit partial[2],int *count,int eye) {
    int mx=(int)player_x,my=(int)player_y,sx=rx<0?-1:1,sy=ry<0?-1:1;
    float ddx=absf(rx)>.000001f?absf(1/rx):1000000;
    float ddy=absf(ry)>.000001f?absf(1/ry):1000000;
    float nx=(rx<0?player_x-mx:mx+1-player_x)*ddx;
    float ny=(ry<0?player_y-my:my+1-player_y)*ddy;
    *count=0;
    for(int step=0;step<MAP_W+MAP_H;++step) {
        int side;float d;
        if(nx<ny){d=nx;nx+=ddx;mx+=sx;side=0;}
        else{d=ny;ny+=ddy;my+=sy;side=1;}
        int t=tile(mx,my);
        if(!t)continue;
        int di=t==5?door_index(mx,my):-1;
        if(di>=0 && (door_open[di]>=16 || (eye && door_open[di]>=8)))continue;
        float coord=side?player_x+d*rx:player_y+d*ry;
        int u=(int)(coord*32)&31;
        if((!side && rx>0)||(side && ry<0))u=31-u;
        Hit h={d>.04f?d:.04f,u,side,t,di};
        if(!eye && di>=0 && door_open[di]>0 && *count<2){partial[(*count)++]=h;continue;}
        return h;
    }
    return (Hit){32,0,0,1,-1};
}
static float blocker(float dx,float dy) {Hit p[2];int n;return trace(dx,dy,p,&n,1).depth;}
static void navigation(void) {
    int seed=(int)player_y*MAP_W+(int)player_x;
    if(nav_seed==seed && (frame&3)!=1)return;
    nav_seed=seed;
    for(int i=0;i<MAP_W*MAP_H;++i)nav_dist[i]=255;
    int head=0,tail=1;nav_queue[0]=seed;nav_dist[seed]=0;
    while(head<tail){int cell=nav_queue[head++],x=cell%MAP_W,y=cell/MAP_W;
        for(int d=0;d<4;++d){int xx=x+dirx[d],yy=y+diry[d],next=yy*MAP_W+xx;
            if((unsigned)xx>=MAP_W || (unsigned)yy>=MAP_H || solid(xx,yy))continue;
            if(nav_dist[next]==255 && nav_dist[cell]<254){nav_dist[next]=nav_dist[cell]+1;nav_queue[tail++]=next;}
        }
    }
}
static void burst(float x,float y,int color) {
    for(int i=0;i<8;++i){Particle *p=&particles[particle_head++&15];
        *p=(Particle){x,y,.55f,(int8_t)((i*7+frame)%9-4),(int8_t)((i*5+frame)%9-4),(int8_t)(4+i%3),10,(uint8_t)color};
    }
}
static int light(float distance,int side,int column) {
    int n=distance<2.3f?3:distance<5?2:distance<9?1:0;
    if(side && n>0)--n;
    if(flashlight && column>42 && column<118 && n<3)++n;
    if(fire_timer>1 && n<3)++n;
    return n;
}
static const uint32_t plane_bits[16]={
    0,0x3,0x300,0x303,0x30000,0x30003,0x30300,0x30303,
    0x3000000,0x3000003,0x3000300,0x3000303,0x3030000,0x3030003,0x3030300,0x3030303};
static unsigned wall_texel(int tile,int u,int row,int shade,int blue) {
    if(tile==4)row=(row+(frame>>1))&31;
    unsigned color=texel(textures[tile+1],row*32+u);
    if(tile==4 && color==13)color=(frame&8)?13:9;
    if(blue && u>21 && u<28 && row>11 && row<21)color=blue_key?12:9;
    return (color==13 || (tile==6 && color==15))?color:light_table[shade][color];
}
/* Four doubled samples become one whole byte in each plane. The opaque
 * wall and floor/ceiling are selected before drawing: no background overdraw.
 * Ray cache shares storage with the navigation queue, which is dead here.
 */
static void world_rows(float dx,float dy) {
    for(int y=TOP;y<=BOTTOM;++y){
        int p=y-HORIZON,is_floor=p>0;
        float distance=p?80.0f/(p>0?p:-p):0;
        int fx=(int)((player_x+distance*(dx+dy))*65536);
        int fy=(int)((player_y+distance*(dy-dx))*65536);
        int sx=(int)(-dy*distance*(2.0f/RAYS)*65536),sy=(int)(dx*distance*(2.0f/RAYS)*65536);
        fx+=sx/2;fy+=sy/2;
        int shade=is_floor?(distance<2.4f?3:distance<6?2:1):(distance<3?2:1);
        for(int group=0;group<40;++group){uint32_t packed=0;
            for(int lane=0;lane<4;++lane){WallColumn *c=&columns[group*4+lane];
                int top=HORIZON-c->height/2;unsigned color;
                if(y>=top && y<top+c->height){int row=(((y-top)*c->step)>>16)&31;
                    unsigned index=column_index[group*4+lane];
                    color=index<32?((column_colors[index][row>>1]>>((row&1)*4))&15):wall_texel(c->meta&7,c->u,row,(c->meta>>3)&3,c->meta&32);
                }else if(p){color=texel(textures[is_floor?0:1],((fy>>11)&31)*32+((fx>>11)&31));
                    color=(!is_floor && color==1)?9:light_table[shade][color];
                }else color=0;
                packed|=plane_bits[color]<<(lane*2);fx+=sx;fy+=sy;
            }
            int off=y*40+group;
            FB[off]=packed;FB[off+8192]=packed>>8;FB[off+16384]=packed>>16;FB[off+24576]=packed>>24;
        }
    }
}
static int wall_strip(int x,Hit hit,int opening) {
    int height=(int)(160.0f/hit.depth);
    if(height<1)height=1;
    int top=HORIZON-height/2,bottom=top+height-1-height*opening/16;
    int first=maxi(TOP,top),last=mini(BOTTOM,bottom);
    int step=(32<<16)/height,pos=(first-top)*step+(opening<<17);
    int shade=light(hit.depth,hit.side,x);
    for(int y=first;y<=last;++y) {
        unsigned color=wall_texel(hit.tile,hit.u,(pos>>16)&31,shade,hit.door==0);
        pixel2(x,y,color);pos+=step;
    }
    return bottom;
}
static void walls(float dx,float dy) {
    unsigned cached=0;
    for(int x=0;x<RAYS;++x) {
        float camera=(2*x+1)*(1.0f/RAYS)-1;
        Hit partial[2];int n;
        Hit h=trace(dx-dy*camera,dy+dx*camera,partial,&n,0);
        wall_depth[x]=h.depth;
        for(int i=0;i<2;++i){door_depth[i][x]=1000000;door_bottom[i][x]=-1;}
        unsigned height=(unsigned)(160.0f/h.depth);if(!height)height=1;
        columns[x]=(WallColumn){(32u<<16)/height,(uint16_t)height,(uint8_t)h.u,
            (uint8_t)(h.tile|(light(h.depth,h.side,x)<<3)|(h.door==0?32:0))};
        unsigned key=columns[x].meta|((unsigned)h.u<<6),index=0;
        while(index<cached && scratch.rays.keys[index]!=key)++index;
        if(index==cached && cached<32){scratch.rays.keys[cached++]=key;
            for(int row=0;row<16;++row)column_colors[index][row]=wall_texel(h.tile,h.u,row*2,(columns[x].meta>>3)&3,h.door==0)|(wall_texel(h.tile,h.u,row*2+1,(columns[x].meta>>3)&3,h.door==0)<<4);}
        column_index[x]=index<32?(uint8_t)index:255;
        for(int i=0;i<n;++i){int door=partial[i].door;
            door_depth[door][x]=partial[i].depth;
            door_uv[door][x]=partial[i].u|(partial[i].side<<5);
        }
    }
}
static void partial_doors(void) {
    for(int x=0;x<RAYS;++x){int first=door_depth[0][x]>door_depth[1][x]?0:1;
        for(int j=0;j<2;++j){int d=first^j;if(door_depth[d][x]>=1000000)continue;
            Hit h={door_depth[d][x],door_uv[d][x]&31,door_uv[d][x]>>5,5,d};
            door_bottom[d][x]=wall_strip(x,h,door_open[d]);
        }
    }
}
static void billboard(float wx,float wy,int kind,int dead,int flash,float dx,float dy) {
    float vx=wx-player_x,vy=wy-player_y,depth=vx*dx+vy*dy;
    if(depth<.15f)return;
    float side=-vx*dy+vy*dx;
    int cx=(int)(80+side/depth*80);
    int height=(int)((dead?27.0f:(!kind || kind>=6)?112.0f:80.0f)/depth);
    if(height<2)return;
    int width=maxi(2,height/3),bottom=(int)(HORIZON+80/depth);
    int top=bottom-height;
    if(!dead)top+=(int)(sine(frame*13+(int)(wx*73))*2);
    int left=cx-width/2;
    int shade=light(depth,0,cx);
    for(int x=maxi(0,left);x<mini(RAYS,left+width);++x) {
        if(depth>=wall_depth[x])continue;
        int tx=(x-left)*32/width;
        for(int y=maxi(TOP,top);y<mini(BOTTOM+1,top+height);++y) {
            int blocked=0;
            for(int i=0;i<2;++i)if(depth>=door_depth[i][x] && y<=door_bottom[i][x])blocked=1;
            if(blocked)continue;
            int ty=(y-top)*32/height;
            int sprite=kind>=6?0:kind;
            if((!kind || kind>=6) && !dead){static const uint8_t walk[]={0,3,4};sprite=walk[((frame>>2)+(int)wx)%3];}
            unsigned color=texel(sprites[sprite],ty*32+tx);
            if(!color)continue;
            if(kind>=6 && (color==2 || color==10)){static const uint8_t colors[]={9,12,10,14};color=colors[kind-6];}
            if(flash)color=15;
            else if(kind==1 || kind==5){} /* the data core/key light themselves */
            else color=light_table[dead?1:shade][color];
            pixel2(x,y,color);
        }
    }
}
static void objects(float dx,float dy) {
    if(mp_active){int order[4],count=0;float depth[4];
        for(int i=0;i<4;++i)if((network.mask&(1<<i)) && i!=network.slot && peers[i].health>0){
            depth[i]=(peers[i].x-player_x)*dx+(peers[i].y-player_y)*dy;int j=count;
            while(j && depth[order[j-1]]<depth[i]){order[j]=order[j-1];--j;}order[j]=i;++count;
        }
        for(int j=0;j<count;++j){int i=order[j];billboard(peers[i].x,peers[i].y,6+i,0,peers[i].hurt_timer,dx,dy);}
        return;
    }
    float distances[DRONE_COUNT+3];int order[DRONE_COUNT+3];
    for(int i=0;i<DRONE_COUNT+3;++i) {
        float x=i<DRONE_COUNT?drones[i].x:i==DRONE_COUNT?CORE_X:i==DRONE_COUNT+1?10.5f:9.5f;
        float y=i<DRONE_COUNT?drones[i].y:i==DRONE_COUNT?CORE_Y:6.5f;
        distances[i]=(x-player_x)*dx+(y-player_y)*dy;order[i]=i;
    }
    for(int i=1;i<DRONE_COUNT+3;++i){int a=order[i],j=i;while(j && distances[order[j-1]]<distances[a]){order[j]=order[j-1];--j;}order[j]=a;}
    for(int k=0;k<DRONE_COUNT+3;++k) {
        int i=order[k];
        if(i<DRONE_COUNT)billboard(drones[i].x,drones[i].y,0,drones[i].hp==0,drones[i].flash,dx,dy);
        if(i==DRONE_COUNT && !core)billboard(CORE_X,CORE_Y,1,0,0,dx,dy);
        if(i==DRONE_COUNT+1 && !medkit)billboard(10.5f,6.5f,2,0,0,dx,dy);
        if(i==DRONE_COUNT+2 && !blue_key)billboard(9.5f,6.5f,5,0,0,dx,dy);
    }
}
static void effects(float dx,float dy) {
    for(int i=0;i<16;++i)if(particles[i].life>0){Particle *p=&particles[i];
        float x=p->x-player_x,y=p->y-player_y,d=x*dx+y*dy;if(d<.1f)continue;
        int sx=(int)(80+(-x*dy+y*dx)*80/d),sy=(int)(HORIZON+(80-160*p->z)/d);
        if((unsigned)sx>=RAYS || sy<TOP || sy>BOTTOM || d>=wall_depth[sx])continue;
        int blocked=0;for(int j=0;j<2;++j)if(d>=door_depth[j][sx] && sy<=door_bottom[j][sx])blocked=1;
        if(!blocked)rect(sx*2,sy,2,2,p->color);
    }
}
static void gun(void) {
    int bob=(int)(sine(walk_phase)*3),kick=fire_timer*2;
    for(int y=125+kick;y<=167;++y) {
        int half=7+(y-125-kick)/3;
        rect(160+bob-half,y,half*2,1,8);
        rect(163+bob,y,mini(5,half-3),1,7);
        if(y>146)rect(148+bob,y,8,1,2);
    }
    rect(152+bob,126+kick,16,5,7);rect(156+bob,125+kick,8,3,15);
    rect(156+bob,132+kick,8,8,0);rect(158+bob,133+kick,4,2,8);
    rect(157+bob,150+kick,6,4,9);rect(164+bob,147+kick,2,2,10);
    if(weapon){rect(142+bob,134+kick,36,34,8);rect(145+bob,135+kick,30,3,15);
        rect(146+bob,139+kick,10,14,0);rect(164+bob,139+kick,10,14,0);rect(157+bob,145+kick,6,23,6);}
    if(fire_timer>1){rect(153+bob,114+kick,14,11,14);rect(158+bob,108+kick,4,23,15);rect(147+bob,118+kick,26,3,14);}
    rect(156,87,3,1,15);rect(162,87,3,1,15);rect(160,84,1,3,15);rect(160,89,1,3,15);
}
static void minimap(void) {
    rect(3,11,MAP_W*3+4,MAP_H*3+4,0);
    for(int y=0;y<MAP_H;++y)for(int x=0;x<MAP_W;++x) {
        int t=tile(x,y),color=t?8:0;
        if(t==5){int d=door_index(x,y);color=door_open[d]>=14?4:14;}
        if(t==6)color=12;
        rect(5+x*3,13+y*3,2,2,color);
    }
    for(int i=0;i<DRONE_COUNT;++i)if(drones[i].hp)pixel(5+(int)(drones[i].x*3),13+(int)(drones[i].y*3),10);
    if(mp_active){for(int i=0;i<4;++i)if((network.mask&(1<<i)) && peers[i].health>0){static const uint8_t colors[]={9,12,10,14};rect(4+(int)(peers[i].x*3),12+(int)(peers[i].y*3),3,3,colors[i]);}}
    if(!mp_active && !core)rect(5+(int)(CORE_X*3),13+(int)(CORE_Y*3),2,2,13);
    if(!blue_key)pixel(33,32,9);
    int px=5+(int)(player_x*3),py=13+(int)(player_y*3);
    rect(px-1,py-1,3,3,15);pixel(px+(int)(sine(angle+256)*4),py+(int)(sine(angle)*4),14);
}
static void reset(void) {
    unpack(&world_map[0][0],map_blobs[sector],MAP_W*MAP_H);
    blue_key=secret_found=notice=weapon=0;tour_x=3;tour_y=8;nav_seed=-1;particle_head=0;
    for(int i=0;i<16;++i)particles[i].life=0;
    player_x=3.5f;player_y=8.5f;angle=0;health=100;ammo=72;kills=0;
    god_mode=cheat_pos=cheat_message=0;ai_on=1;
    core=0;medkit=0;won=0;frame=0;fire_timer=0;cooldown=0;hurt_timer=0;
    map_on=0;flashlight=1;running=0;auto_mode=0;tour_index=0;use_down=0;walk_phase=0;message=0;
    for(int i=0;i<2;++i)door_open[i]=door_goal[i]=0;
    for(int i=0;i<DRONE_COUNT;++i){drones[i]=(Drone){spawn[i][0],spawn[i][1],2,0,i&3};}
}
static void use_door(void) {
    float sx=player_x-5.5f,sy=player_y-10.5f;
    if(!secret_found && sx*sx+sy*sy<3.3f){world_map[10][5]=0;secret_found=1;ammo=mini(99,ammo+24);health=mini(100,health+20);nav_seed=-1;notify(3);abi.sound|=32;return;}
    int best=-1;float distance=3.3f;
    for(int i=0;i<2;++i) {
        float dx=door_pos[i][0]+.5f-player_x,dy=door_pos[i][1]+.5f-player_y;
        float d=dx*dx+dy*dy;
        if(d<distance){distance=d;best=i;}
    }
    if(best==0 && !blue_key){notify(2);return;}
    if(best>=0){door_goal[best]=!door_goal[best];abi.sound|=16;nav_seed=-1;}
}
static void hit_scan(float dx,float dy) {
    if(mp_active){net_hit(dx,dy);return;}
    float limit=blocker(dx,dy);int best=-1;
    for(int i=0;i<DRONE_COUNT;++i)if(drones[i].hp) {
        float x=drones[i].x-player_x,y=drones[i].y-player_y;
        float along=x*dx+y*dy,across=-x*dy+y*dx;
        if(along>.1f && along<limit && absf(across)<.28f){limit=along;best=i;}
    }
    if(best>=0){burst(drones[best].x,drones[best].y,10);drones[best].flash=2;abi.sound|=2;if(--drones[best].hp==0){++kills;abi.sound|=4;}}
    else burst(player_x+dx*(limit-.06f),player_y+dy*(limit-.06f),14);
}
static void shoot(float dx,float dy) {
    int cost=weapon?2:1;if(cooldown || ammo<cost)return;
    ammo-=cost;cooldown=weapon?8:4;fire_timer=3;abi.sound|=1;
    hit_scan(dx,dy);
    if(weapon){hit_scan((dx-dy*.09f)*.9959744f,(dy+dx*.09f)*.9959744f);
        hit_scan((dx+dy*.09f)*.9959744f,(dy-dx*.09f)*.9959744f);}
}
static unsigned tour(void) {
    if(tour_index>tour_lengths[sector])return 0;
    float x=tour_x+.5f-player_x,y=tour_y+.5f-player_y;
    float d2=x*x+y*y;
    if(d2<.035f){if(tour_index<tour_lengths[sector]){int dir=(tour_routes[sector][tour_index>>2]>>((tour_index&3)*2))&3;tour_x+=dirx[dir];tour_y+=diry[dir];++tour_index;}return 0;}
    int fighting=0;
    for(int i=0;i<DRONE_COUNT;++i)if(drones[i].hp){float a=drones[i].x-player_x,b=drones[i].y-player_y,d=a*a+b*b;
        if(d<3 && d>.01f && blocker(a,b)>.99f){x=a;y=b;d2=d;fighting=1;break;}
    }
    float dx=sine(angle+256),dy=sine(angle),cross=dx*y-dy*x,dot=dx*x+dy*y;
    unsigned buttons=0;
    if(cross*cross>d2*.0025f || dot<0)buttons|=cross<0?TURN_LEFT:TURN_RIGHT;
    if(!fighting && dot>0 && cross*cross<d2*.08f)buttons|=FORWARD;
    for(int i=0;i<2;++i)if(!door_goal[i]) {
        float a=door_pos[i][0]+.5f-player_x,b=door_pos[i][1]+.5f-player_y;
        if(a*a+b*b<3.2f && (i || blue_key))door_goal[i]=1;
    }
    if(!secret_found && absf(player_x-5.5f)<1.2f && absf(player_y-10.5f)<1.2f)buttons|=USE;
    for(int i=0;i<DRONE_COUNT;++i)if(drones[i].hp) {
        float a=drones[i].x-player_x,b=drones[i].y-player_y;
        float forward=a*dx+b*dy,side=-a*dy+b*dx;
        if(forward>.1f && forward<5 && absf(side)<.28f)buttons|=FIRE;
    }
    return buttons;
}
static void cheat(unsigned key) {
    static const char code[]="IDDQD";
    static const uint8_t prefix[]={0,1,0,1};
    if(!key)return;
    if(key==254){god_mode^=1;if(god_mode)health=100;cheat_message=35;cheat_pos=0;abi.sound|=128;return;}
    if(key>='a' && key<='z')key-=32;
    /* Match the DDQD suffix: optional I is accepted, and IDDQ alone must
     * not toggle early before the Z80's final FEh event arrives. */
    while(cheat_pos && key!=(unsigned)code[cheat_pos+1])cheat_pos=prefix[cheat_pos-1];
    if(key==(unsigned)code[cheat_pos+1])++cheat_pos;
    if(cheat_pos==4){god_mode^=1;if(god_mode)health=100;cheat_message=35;cheat_pos=0;abi.sound|=128;}
}
static void move_drones(void) {
    if(!ai_on)return;
    navigation();
    for(int i=0;i<DRONE_COUNT;++i)if(drones[i].hp) {
        Drone *d=&drones[i];float x=player_x-d->x,y=player_y-d->y,d2=x*x+y*y;
        float vx=dirx[d->dir&3]*.045f,vy=diry[d->dir&3]*.045f;
        if(d2<49 && d2>.01f && blocker(-x,-y)>.99f)d->dir|=4;
        if(d->dir&4){int xx=(int)d->x,yy=(int)d->y,cell=yy*MAP_W+xx,best=nav_dist[cell];
            if(d2>=1.2f){for(int j=0;j<4;++j){int nx=xx+dirx[j],ny=yy+diry[j],n=ny*MAP_W+nx;
                if((unsigned)nx<MAP_W && (unsigned)ny<MAP_H && nav_dist[n]<best){best=nav_dist[n];x=nx+.5f-d->x;y=ny+.5f-d->y;}}
                float scale=.075f/(absf(x)+absf(y)+.001f);vx=x*scale;vy=y*scale;
            }else vx=vy=0;
        }else if((frame+i*7)%64==0)d->dir=(d->dir+1)&3;
        int moved=0;
        if(can_stand(d->x+vx,d->y)){d->x+=vx;moved|=vx!=0;}
        if(can_stand(d->x,d->y+vy)){d->y+=vy;moved|=vy!=0;}
        if(!moved && !(d->dir&4))d->dir=(d->dir+1)&3;
    }
}
static void update(unsigned key,unsigned buttons) {
    if(key=='1' || key=='2'){sector=key-'1';reset();}
    if(key=='N' && won){sector^=1;reset();}
    if(key=='R' || key==27)reset();
    cheat(key);
    if(key=='M')map_on^=1;
    if(key=='L')flashlight^=1;
    if(key=='Z')running^=1;
    if(key=='V')weapon^=1;
    if(key=='P') {if(auto_mode)auto_mode=0;else{reset();auto_mode=1;}}
    if(buttons&63)auto_mode=0;
    if(auto_mode)buttons=tour();
    else if(!(buttons&63)) { /* Short movement taps survive via the event byte. */
        if(key=='u' || key=='W')buttons|=FORWARD;
        if(key=='d' || key=='S')buttons|=BACKWARD;
        if(key=='l' || key=='A')buttons|=TURN_LEFT;
        if(key=='r' || key=='D')buttons|=TURN_RIGHT;
        if(key=='Q')buttons|=STRAFE_LEFT;
        if(key=='E')buttons|=STRAFE_RIGHT;
    }
    ++frame;
    if(cooldown)--cooldown;if(fire_timer)--fire_timer;if(hurt_timer)--hurt_timer;if(message)--message;
    if(cheat_message)--cheat_message;
    for(int i=0;i<16;++i)if(particles[i].life>0){Particle *p=&particles[i];--p->life;p->x+=p->vx*.015f;p->y+=p->vy*.015f;p->z+=p->vz*.035f;--p->vz;}
    for(int i=0;i<DRONE_COUNT;++i)if(drones[i].flash)--drones[i].flash;
    for(int i=0;i<2;++i) {
        float x=player_x-door_pos[i][0]-.5f,y=player_y-door_pos[i][1]-.5f;
        if((i || blue_key) && !door_goal[i] && absf(x)<.75f && absf(y)<.75f)door_goal[i]=1;
        for(int j=0;j<DRONE_COUNT;++j)if((i || blue_key) && drones[j].hp && absf(drones[j].x-door_pos[i][0]-.5f)<.75f && absf(drones[j].y-door_pos[i][1]-.5f)<.75f)door_goal[i]=1;
        if(door_goal[i] && door_open[i]<16)++door_open[i];
        if(!door_goal[i] && door_open[i]>0)--door_open[i];
    }
    if(health<=0 || won)return;
    if(key=='F' || ((buttons&USE) && !use_down))use_door();
    use_down=buttons&USE;
    if(buttons&TURN_LEFT)angle=(angle-20)&1023;
    if(buttons&TURN_RIGHT)angle=(angle+20)&1023;
    float dx=sine(angle+256),dy=sine(angle);
    int forward=!!(buttons&FORWARD)-!!(buttons&BACKWARD);
    int strafe=!!(buttons&STRAFE_RIGHT)-!!(buttons&STRAFE_LEFT);
    if(forward || strafe) {
        float step=running?.27f:.18f;if(forward && strafe)step*=.70710678f;
        move((dx*forward-dy*strafe)*step,(dy*forward+dx*strafe)*step);walk_phase=(walk_phase+80)&1023;
    }
    if((buttons&FIRE) || key==' ')shoot(dx,dy);
    move_drones();
    float x=player_x-CORE_X,y=player_y-CORE_Y;
    if(!core && x*x+y*y<.22f){core=1;notify(0);abi.sound|=32;}
    x=player_x-9.5f;y=player_y-6.5f;
    if(!blue_key && x*x+y*y<.22f){blue_key=1;notify(1);abi.sound|=32;}
    x=player_x-10.5f;y=player_y-6.5f;
    if(!medkit && x*x+y*y<.22f){medkit=1;health=mini(100,health+25);abi.sound|=32;}
    x=player_x-2.5f;y=player_y-13.5f;
    if(core && blue_key && x*x+y*y<.3f){won=1;auto_mode=0;abi.sound|=64;}
    for(int i=0;i<DRONE_COUNT;++i)if(!god_mode && drones[i].hp && frame%48==i*6) {
        x=drones[i].x-player_x;y=drones[i].y-player_y;float d2=x*x+y*y;
        if(d2<16 && d2>.01f) {
            float d=__builtin_sqrtf(d2);
            if(blocker(x/d,y/d)>d-.1f){health=maxi(0,health-3);hurt_timer=3;abi.sound|=8;}
        }
    }
}
static void hud(void) {
    if(mp_active){net_hud();return;}
    text(2,0,"UNIDOOM / SECTOR ",13);number(98,0,sector+1,1,15);
    if(blue_key)text(112,0,"KEY",9);
    if(secret_found)text(136,0,"S",14);
    if(god_mode)text(160,0,"GOD",14);
    text(205,0,weapon?"SG":"P",14);
    text(244,0,auto_mode?"AUTO TOUR":running?"RUN":"WALK",12);
    rect(0,168,320,10,8);rect(0,168,320,1,7);
    int x=text(3,170,"HP ",7);x=number(x,170,health,3,hurt_timer?10:15);
    x=text(x,170,"  AMMO ",7);x=number(x,170,ammo,2,14);
    x=text(x,170,"  DRONES ",7);x=number(x,170,kills,1,15);
    x=text(x,170,"/8  CORE ",7);text(x,170,core?"YES":"NO",core?13:7);
    text(2,183,"WASD/ARROWS MOVE Q/E STRAFE SPACE FIRE R RESET",7);
    text(2,192,"H HOST J JOIN F USE M MAP B MUSIC V GUN P TOUR",13);
    if(message && health>0 && !won){static const char *const messages[]={"DATA CORE SECURED","BLUE KEY COLLECTED","BLUE KEY REQUIRED","SECRET SUPPLIES"};rect(79,59,164,12,0);text(91,62,messages[notice],13);}
    if(cheat_message){rect(105,43,110,12,0);text(110,46,god_mode?"GOD MODE ON":"GOD MODE OFF",14);}
    if(won || health<=0){rect(76,64,169,28,0);text(91,67,won?"MISSION COMPLETE":"SIGNAL LOST",won?12:10);text(91,80,won?"N NEXT SECTOR":"R TO RESTART",15);}
}
static void render(void) {
    for(int p=0;p<4;++p){uint32_t *words=(uint32_t *)(FB+p*8192);
        for(int i=0;i<80;++i)words[i]=0;
        for(int i=1680;i<2000;++i)words[i]=0;
    }
    float dx=sine(angle+256),dy=sine(angle);
    walls(dx,dy);world_rows(dx,dy);partial_doors();objects(dx,dy);effects(dx,dy);gun();
    if(map_on && !mp_active)minimap();hud();
}
static void present(uint32_t address){
#ifdef UNIDOOM_NATIVE
    volatile uint8_t *dest=video;
#else
    volatile uint8_t *dest=(volatile uint8_t *)(uintptr_t)address;
#endif
    if(address&3){for(int p=0;p<4;++p)for(int i=0;i<8000;++i)dest[p*8192+i]=FB[p*8192+i];}
    else {volatile uint32_t *words=(volatile uint32_t *)dest;
        for(int p=0;p<4;++p)for(int i=0;i<2000;++i)words[p*2048+i]=((uint32_t *)FB)[p*2048+i];}
}
#include "multiplayer.h"

void doom_direct_entry(void) {
    unsigned key=abi.key,buttons=abi.buttons;
    abi.sound=0;
    /* Firmware publishes the current VGA base as a little-endian uint32_t
     * in flash at 08008228h. Validate before initialization or framebuffer
     * writes. Snapshot it for this whole frame; re-read on the next call. */
    uint32_t address=firmware_video_pointer;
    video_address=0;
    if(address<0x10000000u || address>0x10008000u)return;
    video_address=address;
    if(!abi.initialized){abi.initialized=1;sector=0;unpack(art,art_blob,ART_BYTES);reset();mp_active=0;processed_tick=0xffff;key=0;buttons=0;}
    if(network.mode){
        /* Network lobbies and matches never inherit single-player assists. */
        map_on=god_mode=cheat_pos=cheat_message=0;
        if(network.mode==2){
            if(!mp_active)net_reset();
            if(!network.ui && processed_tick!=network.tick){net_tick();processed_tick=network.tick;}
            net_load(network.slot);
            if(key=='L')flashlight^=1;
        }
        render();net_overlay();
    }else {if(mp_active){mp_active=0;reset();}update(key,buttons);render();}
    present(address);
#ifndef UNIDOOM_NATIVE
    __asm__ volatile ("dmb" ::: "memory");
#endif
}
#ifdef UNIDOOM_NATIVE
void native_key(unsigned key,unsigned buttons){abi.key=key;abi.buttons=buttons;doom_direct_entry();}
void native_cold(void){network=(Network){0};abi.initialized=0;video_address=0;firmware_video_pointer=0x10001f80;for(int i=0;i<32768;++i)framebuffer[i]=video[i]=0xa5;}
void native_set_video_pointer(uint32_t address){firmware_video_pointer=address;}
uint32_t native_video_address(void){return video_address;}
const uint8_t *native_frame(void){return video;}
const uint8_t *native_back_frame(void){return FB;}
int native_state(int n) {
    const int v[]={angle,health,ammo,kills,core,medkit,won,frame,fire_timer,cooldown,hurt_timer,
                   map_on,flashlight,running,auto_mode,tour_index,use_down,walk_phase,message,
                   door_open[0],door_open[1],door_goal[0],door_goal[1],god_mode,cheat_pos,cheat_message,ai_on,sector,blue_key,secret_found,notice,tour_x,tour_y,nav_seed,weapon};return v[n];
}
float native_x(void){return player_x;}float native_y(void){return player_y;}
int native_drone(int n){return drones[n].hp;}
const float *native_depth(void){return wall_depth;}
void native_pose(float x,float y,int a){player_x=x;player_y=y;angle=a&1023;auto_mode=0;abi.key=0;abi.buttons=0;doom_direct_entry();}
void native_set_pose(float x,float y,int a){player_x=x;player_y=y;angle=a&1023;auto_mode=0;}
int native_can_stand(float x,float y){return can_stand(x,y);}
const float *native_door_depth(int i){return door_depth[i];}
void native_test_door(int i,int amount){door_open[i]=amount;door_goal[i]=amount!=0;}
void native_test_drone(int i,float x,float y,int hp){drones[i]=(Drone){x,y,hp,0,i&3};}
float native_drone_x(int i){return drones[i].x;}float native_drone_y(int i){return drones[i].y;}
void native_ai(int enabled){ai_on=enabled;}
unsigned native_sound(void){return abi.sound;}
int native_tile(int x,int y){return tile(x,y);}
int native_nav(int x,int y){nav_seed=-1;navigation();return nav_dist[y*MAP_W+x];}
const uint8_t *native_flow(void){nav_seed=-1;navigation();return nav_dist;}
const uint8_t *native_art(void){return art;}
void native_alert(int i){drones[i].dir|=4;}
unsigned native_particles(void){unsigned n=0;for(int i=0;i<16;++i)n+=particles[i].life>0;return n;}
void native_net(unsigned slot,unsigned mask,unsigned tick,const uint8_t *inputs){network.mode=2;network.slot=slot;network.mask=mask;network.tick=tick;network.ui=0;for(int i=0;i<8;++i)network.input[i/2][i%2]=inputs[i];abi.key=0;abi.buttons=0;doom_direct_entry();}
unsigned native_net_hash(void){return network.hash;}
const void *native_peers(void){return peers;}
void native_net_pose(int i,float x,float y,int a){peers[i].x=x;peers[i].y=y;peers[i].angle=a;}
void native_net_health(int i,int hp){peers[i].health=hp;peers[i].shield=0;}
void native_tick(unsigned key,unsigned buttons){abi.sound=0;update(key,buttons);}
void native_render(void){render();present(video_address);}
#endif
