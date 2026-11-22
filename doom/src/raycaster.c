/* UniDoom: original miniature sector crawler for UniCard OpenCPU.
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

typedef struct {uint8_t key,initialized,buttons,reserved;} ABI;
#ifdef UNIDOOM_NATIVE
ABI abi;
static uint8_t framebuffer[32768];
#define FB framebuffer
#else
extern volatile ABI abi;
#define FB ((uint8_t *)0x20028000)
#endif
typedef struct {float x,y;int hp,flash;} Drone;
typedef struct {float depth;int u,side,tile,door;} Hit;
static float player_x,player_y;
static int angle,health,ammo,kills,core,medkit,won,frame,fire_timer,cooldown,hurt_timer;
static int map_on,flashlight,running,auto_mode,tour_index,use_down,walk_phase,message;
static int door_open[2],door_goal[2];
static Drone drones[4];
static float wall_depth[RAYS],door_depth[2][RAYS];
static int16_t door_bottom[2][RAYS];
static const uint8_t door_pos[2][2]={{6,3},{6,13}};
static const float spawn[4][2]={{10.5f,8.5f},{3.5f,6.5f},{11.5f,2.5f},{10.5f,13.5f}};

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
        uint8_t *dest=FB+p*8192+off;
        *dest=(*dest&~mask)|((color&(1u<<p))?mask:0);
    }
}
static void pixel2(int x,int y,unsigned color) {
    unsigned off=y*40+(x>>2),mask=3u<<((x&3)*2);
    for(unsigned p=0;p<4;++p) {
        uint8_t *dest=FB+p*8192+off;
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
    if((unsigned)x>=16 || (unsigned)y>=16)return 1;
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
    return x>.21f && y>.21f && x<15.79f && y<15.79f;
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
    for(int step=0;step<64;++step) {
        int side;float d;
        if(nx<ny){d=nx;nx+=ddx;mx+=sx;side=0;}
        else{d=ny;ny+=ddy;my+=sy;side=1;}
        int t=tile(mx,my);
        if(!t)continue;
        int di=t==5?door_index(mx,my):-1;
        if(di>=0 && (door_open[di]>=16 || (eye && door_open[di]>=8)))continue;
        float coord=side?player_x+d*rx:player_y+d*ry;
        int u=(int)(coord*16)&15;
        if((!side && rx>0)||(side && ry<0))u=15-u;
        Hit h={d>.04f?d:.04f,u,side,t,di};
        if(!eye && di>=0 && door_open[di]>0 && *count<2){partial[(*count)++]=h;continue;}
        return h;
    }
    return (Hit){32,0,0,1,-1};
}
static float blocker(float dx,float dy) {Hit p[2];int n;return trace(dx,dy,p,&n,1).depth;}
static int light(float distance,int side,int column) {
    int n=distance<1.8f?3:distance<3.8f?2:distance<6.5f?1:0;
    if(side && n>0)--n;
    if(flashlight && column>42 && column<118 && n<3)++n;
    if(fire_timer>1 && n<3)++n;
    return n;
}
static void floors(float dx,float dy) {
    for(int y=TOP;y<=BOTTOM;++y) {
        int p=y-HORIZON;int floor=p>0;
        if(!p){for(int x=0;x<RAYS;++x)pixel2(x,y,0);continue;}
        float distance=80.0f/(p>0?p:-p);
        float leftx=dx+dy,lefty=dy-dx;
        int fx=(int)((player_x+distance*leftx)*65536);
        int fy=(int)((player_y+distance*lefty)*65536);
        int stepx=(int)(-dy*distance*(2.0f/RAYS)*65536);
        int stepy=(int)(dx*distance*(2.0f/RAYS)*65536);
        fx+=stepx/2;fy+=stepy/2;
        int shade=floor?(distance<2.4f?2:distance<5?1:0):(distance<2?1:0);
        for(int x=0;x<RAYS;++x) {
            unsigned color=textures[floor?0:1][((fy>>12)&15)*16+((fx>>12)&15)];
            if(!floor && color==1)color=9; /* ceiling conduits are emissive */
            else color=light_table[shade][color];
            pixel2(x,y,color);fx+=stepx;fy+=stepy;
        }
    }
}
static int wall_strip(int x,Hit hit,int opening) {
    int height=(int)(160.0f/hit.depth);
    if(height<1)height=1;
    int top=HORIZON-height/2,bottom=top+height-1-height*opening/16;
    int first=maxi(TOP,top),last=mini(BOTTOM,bottom);
    int step=(16<<16)/height,pos=(first-top)*step+(opening<<16);
    int shade=light(hit.depth,hit.side,x);
    const uint8_t *tex=textures[hit.tile+1];
    for(int y=first;y<=last;++y) {
        unsigned color=tex[((pos>>16)&15)*16+hit.u];
        color=(color==13 || (hit.tile==6 && color==15))?color:light_table[shade][color];
        pixel2(x,y,color);pos+=step;
    }
    return bottom;
}
static void walls(float dx,float dy) {
    for(int x=0;x<RAYS;++x) {
        float camera=(2*x+1)*(1.0f/RAYS)-1;
        Hit partial[2];int n;
        Hit h=trace(dx-dy*camera,dy+dx*camera,partial,&n,0);
        wall_depth[x]=h.depth;
        for(int i=0;i<2;++i){door_depth[i][x]=1000000;door_bottom[i][x]=-1;}
        wall_strip(x,h,0);
        for(int i=n-1;i>=0;--i) {
            int door=partial[i].door;
            door_depth[door][x]=partial[i].depth;
            door_bottom[door][x]=wall_strip(x,partial[i],door_open[door]);
        }
    }
}
static void billboard(float wx,float wy,int kind,int dead,int flash,float dx,float dy) {
    float vx=wx-player_x,vy=wy-player_y,depth=vx*dx+vy*dy;
    if(depth<.15f)return;
    float side=-vx*dy+vy*dx;
    int cx=(int)(80+side/depth*80);
    int height=(int)((dead?27.0f:kind==0?112.0f:80.0f)/depth);
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
            unsigned color=sprites[kind][ty*32+tx];
            if(!color)continue;
            if(flash)color=15;
            else if(kind==1){} /* the data core lights itself */
            else color=light_table[dead?1:shade][color];
            pixel2(x,y,color);
        }
    }
}
static void objects(float dx,float dy) {
    float distances[6];int order[6];
    for(int i=0;i<6;++i) {
        float x=i<4?drones[i].x:i==4?12.5f:10.5f;
        float y=i<4?drones[i].y:i==4?3.5f:6.5f;
        distances[i]=(x-player_x)*dx+(y-player_y)*dy;order[i]=i;
    }
    for(int i=1;i<6;++i){int a=order[i],j=i;while(j && distances[order[j-1]]<distances[a]){order[j]=order[j-1];--j;}order[j]=a;}
    for(int k=0;k<6;++k) {
        int i=order[k];
        if(i<4)billboard(drones[i].x,drones[i].y,0,drones[i].hp==0,drones[i].flash,dx,dy);
        if(i==4 && !core)billboard(12.5f,3.5f,1,0,0,dx,dy);
        if(i==5 && !medkit)billboard(10.5f,6.5f,2,0,0,dx,dy);
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
    if(fire_timer>1){rect(153+bob,114+kick,14,11,14);rect(158+bob,108+kick,4,23,15);rect(147+bob,118+kick,26,3,14);}
    rect(156,87,3,1,15);rect(162,87,3,1,15);rect(160,84,1,3,15);rect(160,89,1,3,15);
}
static void minimap(void) {
    rect(3,11,52,52,0);
    for(int y=0;y<16;++y)for(int x=0;x<16;++x) {
        int t=tile(x,y),color=t?8:0;
        if(t==5){int d=door_index(x,y);color=door_open[d]>=14?4:14;}
        if(t==6)color=12;
        rect(5+x*3,13+y*3,2,2,color);
    }
    for(int i=0;i<4;++i)if(drones[i].hp)pixel(5+(int)(drones[i].x*3),13+(int)(drones[i].y*3),10);
    if(!core)rect(41,22,2,2,13);
    int px=5+(int)(player_x*3),py=13+(int)(player_y*3);
    rect(px-1,py-1,3,3,15);pixel(px+(int)(sine(angle+256)*4),py+(int)(sine(angle)*4),14);
}
static void reset(void) {
    player_x=3.5f;player_y=8.5f;angle=0;health=100;ammo=36;kills=0;
    core=0;medkit=0;won=0;frame=0;fire_timer=0;cooldown=0;hurt_timer=0;
    map_on=0;flashlight=1;running=0;auto_mode=0;tour_index=1;use_down=0;walk_phase=0;message=0;
    for(int i=0;i<2;++i)door_open[i]=door_goal[i]=0;
    for(int i=0;i<4;++i){drones[i].x=spawn[i][0];drones[i].y=spawn[i][1];drones[i].hp=2;drones[i].flash=0;}
}
static void use_door(void) {
    int best=-1;float distance=3.3f;
    for(int i=0;i<2;++i) {
        float dx=door_pos[i][0]+.5f-player_x,dy=door_pos[i][1]+.5f-player_y;
        float d=dx*dx+dy*dy;
        if(d<distance){distance=d;best=i;}
    }
    if(best>=0)door_goal[best]=!door_goal[best];
}
static void shoot(float dx,float dy) {
    if(cooldown || ammo<=0)return;
    --ammo;cooldown=4;fire_timer=3;
    float limit=blocker(dx,dy);int best=-1;
    for(int i=0;i<4;++i)if(drones[i].hp) {
        float x=drones[i].x-player_x,y=drones[i].y-player_y;
        float along=x*dx+y*dy,across=-x*dy+y*dx;
        if(along>.1f && along<limit && absf(across)<.28f){limit=along;best=i;}
    }
    if(best>=0){drones[best].flash=2;if(--drones[best].hp==0)++kills;}
}
static unsigned tour(void) {
    if(tour_index>=TOUR_POINTS)return 0;
    float x=tour_path[tour_index][0]+.5f-player_x,y=tour_path[tour_index][1]+.5f-player_y;
    float d2=x*x+y*y;
    if(d2<.035f){++tour_index;return 0;}
    float dx=sine(angle+256),dy=sine(angle),cross=dx*y-dy*x,dot=dx*x+dy*y;
    unsigned buttons=0;
    if(cross>.06f)buttons|=TURN_RIGHT;
    if(cross<-.06f)buttons|=TURN_LEFT;
    if(dot>0 && cross*cross<d2*.08f)buttons|=FORWARD;
    for(int i=0;i<2;++i)if(!door_goal[i]) {
        float a=door_pos[i][0]+.5f-player_x,b=door_pos[i][1]+.5f-player_y;
        if(a*a+b*b<3.2f)door_goal[i]=1;
    }
    for(int i=0;i<4;++i)if(drones[i].hp) {
        float a=drones[i].x-player_x,b=drones[i].y-player_y;
        float forward=a*dx+b*dy,side=-a*dy+b*dx;
        if(forward>.1f && forward<5 && absf(side)<.28f)buttons|=FIRE;
    }
    return buttons;
}
static void update(unsigned key,unsigned buttons) {
    if(key=='R' || key==27)reset();
    if(key=='M')map_on^=1;
    if(key=='L')flashlight^=1;
    if(key=='Z')running^=1;
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
    for(int i=0;i<4;++i)if(drones[i].flash)--drones[i].flash;
    for(int i=0;i<2;++i) {
        float x=player_x-door_pos[i][0]-.5f,y=player_y-door_pos[i][1]-.5f;
        if(!door_goal[i] && absf(x)<.75f && absf(y)<.75f)door_goal[i]=1;
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
    float x=player_x-12.5f,y=player_y-3.5f;
    if(!core && x*x+y*y<.22f){core=1;message=36;}
    x=player_x-10.5f;y=player_y-6.5f;
    if(!medkit && x*x+y*y<.22f){medkit=1;health=mini(100,health+25);}
    x=player_x-2.5f;y=player_y-13.5f;
    if(core && x*x+y*y<.3f){won=1;auto_mode=0;}
    for(int i=0;i<4;++i)if(drones[i].hp && frame%24==i*6) {
        x=drones[i].x-player_x;y=drones[i].y-player_y;float d2=x*x+y*y;
        if(d2<16 && d2>.01f) {
            float d=__builtin_sqrtf(d2);
            if(blocker(x/d,y/d)>d-.1f){health=maxi(0,health-3);hurt_timer=3;}
        }
    }
}
static void hud(void) {
    text(2,0,"UNIDOOM / SECTOR 01",13);
    text(244,0,auto_mode?"AUTO TOUR":running?"RUN":"WALK",12);
    rect(0,168,320,10,8);rect(0,168,320,1,7);
    int x=text(3,170,"HP ",7);x=number(x,170,health,3,hurt_timer?10:15);
    x=text(x,170,"  AMMO ",7);x=number(x,170,ammo,2,14);
    x=text(x,170,"  DRONES ",7);x=number(x,170,kills,1,15);
    x=text(x,170,"/4  CORE ",7);text(x,170,core?"YES":"NO",core?13:7);
    text(2,183,"ARROWS/WASD MOVE Q/E STRAFE SPACE FIRE",7);
    text(2,192,"F DOOR M MAP P TOUR L LIGHT Z RUN R RESET",13);
    if(message && health>0 && !won){rect(79,59,164,18,0);text(91,61,"DATA CORE SECURED",13);text(91,69,"RETURN TO EXIT",15);}
    if(won || health<=0){rect(76,64,169,28,0);text(91,67,won?"MISSION COMPLETE":"SIGNAL LOST",won?12:10);text(91,80,"R TO RESTART",15);}
}
static void render(void) {
    for(int i=0;i<32768;++i)FB[i]=0;
    float dx=sine(angle+256),dy=sine(angle);
    floors(dx,dy);walls(dx,dy);objects(dx,dy);gun();
    if(map_on)minimap();hud();
}
void doom_entry(void) {
    unsigned key=abi.key,buttons=abi.buttons;
    if(!abi.initialized){abi.initialized=1;reset();key=0;buttons=0;}
    update(key,buttons);render();
}
#ifdef UNIDOOM_NATIVE
void native_key(unsigned key,unsigned buttons){abi.key=key;abi.buttons=buttons;doom_entry();}
void native_cold(void){abi.initialized=0;}
const uint8_t *native_frame(void){return FB;}
int native_state(int n) {
    const int v[]={angle,health,ammo,kills,core,medkit,won,frame,fire_timer,cooldown,hurt_timer,
                   map_on,flashlight,running,auto_mode,tour_index,use_down,walk_phase,message,
                   door_open[0],door_open[1],door_goal[0],door_goal[1]};return v[n];
}
float native_x(void){return player_x;}float native_y(void){return player_y;}
int native_drone(int n){return drones[n].hp;}
const float *native_depth(void){return wall_depth;}
void native_pose(float x,float y,int a){player_x=x;player_y=y;angle=a&1023;auto_mode=0;abi.key=0;abi.buttons=0;doom_entry();}
void native_set_pose(float x,float y,int a){player_x=x;player_y=y;angle=a&1023;auto_mode=0;}
int native_can_stand(float x,float y){return can_stand(x,y);}
const float *native_door_depth(int i){return door_depth[i];}
void native_test_door(int i,int amount){door_open[i]=amount;door_goal[i]=amount!=0;}
void native_test_drone(int i,float x,float y,int hp){drones[i]=(Drone){x,y,hp,0};}
void native_render(void){render();}
#endif
