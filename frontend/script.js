const video = document.getElementById("video");
const overlay = document.getElementById("overlay");

const ctx = overlay.getContext("2d");

const socket = new WebSocket("ws://localhost:8000/ws");

let latestObjects = [];
let latestHaptic = {};

socket.onmessage = (event)=>{

    const data = JSON.parse(event.data);

    latestObjects = data.objects;

    latestHaptic = data.haptic;

};

navigator.mediaDevices
.getUserMedia({
    video:true
})
.then(stream=>{

    video.srcObject = stream;

    const canvas = document.createElement("canvas");
    const captureCtx = canvas.getContext("2d");

    function drawOverlay(){

        overlay.width = video.videoWidth;
        overlay.height = video.videoHeight;

        ctx.clearRect(
            0,
            0,
            overlay.width,
            overlay.height
        );

        ctx.lineWidth = 3;

        ctx.font = "18px Arial";

        latestObjects.forEach(obj=>{

            const [x1,y1,x2,y2] = obj.bbox;

            // Bounding Box

            ctx.strokeStyle="#00ff66";

            ctx.strokeRect(
                x1,
                y1,
                x2-x1,
                y2-y1
            );

            // Label Background

            ctx.fillStyle="#00ff66";

            ctx.fillRect(
                x1,
                y1-28,
                250,
                26
            );

            // Label Text

            ctx.fillStyle="black";

            ctx.fillText(

                `${obj.label} | D:${obj.depth} | ${obj.direction} | P${obj.priority}`,

                x1+5,

                y1-9

            );

        });

        // Draw Haptic Status

        ctx.fillStyle="rgba(0,0,0,0.7)";

        ctx.fillRect(
            10,
            10,
            260,
            70
        );

        ctx.fillStyle="white";

        ctx.font="22px Arial";

        ctx.fillText(

            `LEFT : ${latestHaptic.left || 0}`,

            20,

            35

        );

        ctx.fillText(

            `CENTER : ${latestHaptic.center || 0}`,

            20,

            60

        );

        ctx.fillText(

            `RIGHT : ${latestHaptic.right || 0}`,

            20,

            85

        );

        requestAnimationFrame(drawOverlay);

    }

    drawOverlay();

    setInterval(()=>{

        if(video.videoWidth===0)return;

        canvas.width=video.videoWidth;
        canvas.height=video.videoHeight;

        captureCtx.drawImage(video,0,0);

        canvas.toBlob(blob=>{

            if(
                blob &&
                socket.readyState===WebSocket.OPEN
            ){

                blob.arrayBuffer().then(buffer=>{

                    socket.send(buffer);

                });

            }

        },"image/jpeg",0.7);

    },100);

});