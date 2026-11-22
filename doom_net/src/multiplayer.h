/* UniDoom NET deathmatch, deterministic slot order; no network I/O on ARM. */
static void net_load(int i){NetPlayer *p=&peers[i];player_x=p->x;player_y=p->y;
#define LOAD(n) n=p->n;
    PLAYER_FIELDS(LOAD)
#undef LOAD
}
static void net_store(int i){NetPlayer *p=&peers[i];p->x=player_x;p->y=player_y;
#define STORE(n) p->n=n;
    PLAYER_FIELDS(STORE)
#undef STORE
}
static void net_spawn(int i){
    static const float spawn_x[]={3.5f,28.5f,2.5f,19.5f},spawn_y[]={8.5f,3.5f,13.5f,20.5f};
    NetPlayer *p=&peers[i];int score=p->score;
    for(unsigned j=0;j<sizeof(*p);++j)((volatile uint8_t *)p)[j]=0;p->score=score;p->health=100;p->ammo=72;p->shield=30;p->angle=(i&1)?512:0;
    p->x=spawn_x[i];p->y=spawn_y[i];
    /* Both maps use these walkable landmarks. Never spawn inside a wall. */
    if(!can_stand(p->x,p->y)){p->x=3.5f;p->y=8.5f;}
}
static void net_reset(void){
    if(!mp_active)sector=network.sector&1;
    reset();mp_active=1;ai_on=0;blue_key=1;core=medkit=1;
    for(int i=0;i<DRONE_COUNT;++i)drones[i].hp=0;
    for(int i=0;i<4;++i){peers[i].score=0;net_spawn(i);}
    processed_tick=0xffff;
}
static void net_hit(float dx,float dy){
    float limit=blocker(dx,dy);int target=-1;
    for(int i=0;i<4;++i)if(i!=active_peer && (network.mask&(1<<i)) && peers[i].health>0){
        float x=peers[i].x-player_x,y=peers[i].y-player_y,along=x*dx+y*dy,across=-x*dy+y*dx;
        if(along>.1f && along<limit && absf(across)<.28f){limit=along;target=i;}
    }
    if(target>=0){NetPlayer *p=&peers[target];
        burst(p->x,p->y,10);
        if(p->shield)return;
        p->hurt_timer=3;p->health=maxi(0,p->health-25);
        if(target==network.slot)abi.sound|=8;
        if(!p->health){p->respawn=30;++peers[active_peer].score;
            if(active_peer==network.slot)abi.sound|=4;
            if(peers[active_peer].score>=10)won=active_peer+1;
        }
    }else burst(player_x+dx*(limit-.06f),player_y+dy*(limit-.06f),14);
}
static void net_tick(void){
    unsigned host=network.input[0][0];
    if(host=='N'){sector^=1;net_reset();}
    else if(host=='R')net_reset();
    ++frame;
    for(int i=0;i<16;++i)if(particles[i].life>0){Particle *p=&particles[i];--p->life;p->x+=p->vx*.015f;p->y+=p->vy*.015f;p->z+=p->vz*.035f;--p->vz;}
    if(!won){
        for(int i=0;i<2;++i){for(int j=0;j<4;++j)if((network.mask&(1<<j)) && peers[j].health>0 && absf(peers[j].x-door_pos[i][0]-.5f)<.75f && absf(peers[j].y-door_pos[i][1]-.5f)<.75f)door_goal[i]=1;
            if(door_goal[i] && door_open[i]<16)++door_open[i];
            if(!door_goal[i] && door_open[i]>0)--door_open[i];}
        /* Move every participant before resolving weapons in slot order. */
        for(int i=0;i<4;++i)if(network.mask&(1<<i)){
            NetPlayer *p=&peers[i];if(p->shield)--p->shield;
            if(p->health<=0){if(p->respawn && !--p->respawn)net_spawn(i);continue;}
            net_load(i);unsigned key=network.input[i][0],buttons=network.input[i][1];
            if(cooldown)--cooldown;if(fire_timer)--fire_timer;if(hurt_timer)--hurt_timer;
            if(key=='V')weapon^=1;if(key=='Z')running^=1;
            if(key=='F' || ((buttons&USE) && !use_down))use_door();use_down=buttons&USE;
            if(buttons&TURN_LEFT)angle=(angle-20)&1023;if(buttons&TURN_RIGHT)angle=(angle+20)&1023;
            float dx=sine(angle+256),dy=sine(angle);
            int forward=!!(buttons&FORWARD)-!!(buttons&BACKWARD),strafe=!!(buttons&STRAFE_RIGHT)-!!(buttons&STRAFE_LEFT);
            if(forward || strafe){float step=running?.27f:.18f;if(forward && strafe)step*=.70710678f;
                move((dx*forward-dy*strafe)*step,(dy*forward+dx*strafe)*step);walk_phase=(walk_phase+80)&1023;}
            net_store(i);
        }
        for(int i=0;i<4 && !won;++i)if((network.mask&(1<<i)) && peers[i].health>0){
            net_load(i);active_peer=i;
            if((network.input[i][1]&FIRE) || network.input[i][0]==' '){
                /* Shooting ends spawn protection. Effects are local sounds. */
                peers[i].shield=0;unsigned sound=abi.sound;shoot(sine(angle+256),sine(angle));
                if(i!=network.slot)abi.sound=sound|(abi.sound&12);
            }
            net_store(i);
        }
    }
    /* Exclude camera, rendering caches and local HUD toggles from state hash. */
    uint16_t hash=0x4d5a;
#define HASH_BYTE(v) hash=(uint16_t)((hash<<5)|(hash>>11))^(uint8_t)(v)
    for(unsigned i=0;i<sizeof(peers);++i){HASH_BYTE(((uint8_t *)peers)[i]);}
    for(unsigned i=0;i<sizeof(world_map);++i){HASH_BYTE(((uint8_t *)world_map)[i]);}
    for(unsigned i=0;i<sizeof(door_open);++i){HASH_BYTE(((uint8_t *)door_open)[i]);HASH_BYTE(((uint8_t *)door_goal)[i]);}
    HASH_BYTE(frame);HASH_BYTE(frame>>8);HASH_BYTE(sector);HASH_BYTE(won);HASH_BYTE(secret_found);
#undef HASH_BYTE
    network.hash=hash;
}
static void net_hud(void){
    static const uint8_t colors[]={9,12,10,14};
    text(2,0,"DEATHMATCH / SECTOR ",13);number(116,0,sector+1,1,15);
    int x=text(160,0,"YOU P",7);number(x,0,network.slot+1,1,colors[network.slot]);
    rect(0,168,320,10,8);int xhp=text(3,170,"HP ",7);number(xhp,170,health,3,hurt_timer?10:15);
    xhp=text(66,170,weapon?"SG ":"P ",7);number(xhp,170,ammo,2,14);
    for(int i=0;i<4;++i)if(network.mask&(1<<i)){int x=124+i*48;x=text(x,170,"P",colors[i]);x=number(x,170,i+1,1,colors[i]);number(x+3,170,peers[i].score,2,15);}
    text(2,183,"SPACE FIRE F DOOR V GUN Z RUN M MAP B MUSIC",7);
    text(2,192,"H HOST J JOIN ESC LEAVE / HOST R RESET N MAP",13);
    if(won || health<=0){rect(82,64,156,28,0);
        if(won){int x=text(98,67,"WINNER P",14);number(x,67,won,1,colors[won-1]);text(98,80,"HOST: R REMATCH",15);}
        else{text(98,67,"FRAGGED",10);text(98,80,"RESPAWNING...",15);}
    }
}
static void net_overlay(void){
    if(!network.ui)return;
    rect(34,37,252,108,0);text(64,44,"UNIDOOM NET / DEATHMATCH",13);
    if(network.ui==1){text(58,62,"ROOM",7);char code[5];for(int i=0;i<4;++i)code[i]=network.code[i];code[4]=0;text(94,62,code,15);
        text(58,80,"JOINED / NEEDED",7);number(166,80,network.mask,1,15);number(184,80,network.slots,1,12);
        text(58,98,"SPACE: READY (HOST LAST)",14);
    }else if(network.ui==2){text(58,65,"ENTER FOUR LETTER ROOM CODE",7);char code[5];for(int i=0;i<4;++i)code[i]=network.code[i]?network.code[i]:'_';code[4]=0;text(130,86,code,15);
    }else if(network.ui==3)text(76,75,"HOW MANY PLAYERS? 2 / 3 / 4",14);
    else if(network.ui==4)text(76,75,"WAITING FOR PLAYERS...",14);
    else if(network.ui==6){text(58,68,"UNICARD NET FIRMWARE REQUIRED",10);text(58,88,"CHECK INFO FEATURE BIT 08",7);}
    else{text(58,68,"NETWORK STOPPED / ERROR",10);number(202,68,network.error,2,15);text(58,88,"CHECK CABLE RELAY AND BUILD",7);}
    text(76,124,"ESC: BACK TO SINGLE PLAYER",12);
}
